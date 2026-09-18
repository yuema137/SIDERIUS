# execute_tools/model_input_dtype.py
"""Resolve the concrete dtype fed to a model's forward — Step 03 §4a.1 (A-1).

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§4a (dataset dtype and model-boundary dtype are DISTINCT authorities),
**§4a.1 AMENDMENT A-1**, §21, §24.9 Q7/Q8.

This is the INPUT-side twin of ``ml_models.loss_models_sandbox
.get_target_torch_dtype`` — the target-side routing that audit row 12
found already contract-keyed, on the line *adjacent* to the model-name
branch this module replaces:

```text
train_engine_sandbox.py:660   INPUT dtype   <- model NAME branch      (before)
train_engine_sandbox.py:668   TARGET dtype  <- get_target_torch_dtype (already)
```

**The rule (A-1).** The contract owns dtype ADMISSIBILITY; execution owns
the concrete representation:

```text
model-admissible  ∩  runtime-supported   ->  deterministic concrete dtype
                                         ->  empty = typed fail-closed
```

**A site preference is compatibility behaviour, never model semantics.**
Legacy callers without a task composition retain the historical int32
training and int64 inference preferences. A composed run instead selects one
concrete dtype from the model's declaration for every execution site. For a
declaration admitting int64 and int32 in that order, both sites use int64.
This prevents a model from passing inference checks yet failing when the
training runtime supplies a different, still-admissible dtype.

**Expressiveness exceeds validated support.** A contract may declare
``float16``, ``bfloat16``, ``complex64`` and so on — the schema has no
closed vocabulary. This module names only what the adaptation path is
*proven* to materialize, and a requirement outside that set fails closed
rather than being quietly attempted (§24.9 Q8/Q14).

It lives in ``execute_tools`` rather than ``ml_models`` because it needs
both ``torch`` and the contract from ``agent.schemas``, and ``ml_models``
must not import ``agent``.
"""

from __future__ import annotations

import torch

from agent.schemas.model_io_contract import ModelIOContract
from ml_models.models_format_sandbox import DtypeAdmissibility

#: Concrete dtypes the current data→model adaptation path is PROVEN to
#: materialize. Every one is executed by baseline A6 against every builtin.
#:
#: This is the runtime-capability half of A-1's intersection, and it is
#: deliberately narrower than what the contract can express. Adding an entry
#: is a claim that the adaptation path materializes it — it needs evidence,
#: not just a mapping row.
RUNTIME_SUPPORTED_DTYPES: dict[str, torch.dtype] = {
    "int64": torch.int64,
    "int32": torch.int32,
    "float32": torch.float32,
}

#: Legacy site preferences are retained for callers without a task contract.
TRAINING_SITE_DTYPE = "int32"
INFERENCE_SITE_DTYPE = "int64"


class UnsupportedModelInputDtypeError(RuntimeError):
    """No concrete dtype is both model-admissible and runtime-supported.

    The typed fail-closed of §24.9 Q8. Deliberately NOT a silent coercion to
    something plausible: a wrong dtype at the model boundary is invisible to
    every prompt-level and schema-level test and only manifests in real
    training, which is failure class (b) of §7.
    """


def resolve_model_input_dtype(
    admissibility: DtypeAdmissibility,
    *,
    site_preference: str,
) -> torch.dtype:
    """The concrete dtype to feed this model's forward at this site.

    Args:
        admissibility: what the model boundary accepts — from the model's own
            declaration when it has one, otherwise the task's Model-I/O
            contract.
        site_preference: the concrete dtype this execution site has always
            fed. Honoured whenever admissible; never treated as a constraint.

    Returns:
        The resolved ``torch.dtype``.

    Raises:
        UnsupportedModelInputDtypeError: the intersection is empty.
    """
    supported = [name for name in admissibility.admissible if name in RUNTIME_SUPPORTED_DTYPES]
    if not supported:
        raise UnsupportedModelInputDtypeError(
            f"no concrete dtype satisfies the model input requirement: declared "
            f"admissible={list(admissibility.admissible)}, runtime-supported="
            f"{sorted(RUNTIME_SUPPORTED_DTYPES)}. The intersection is empty, so "
            "there is nothing correct to feed the model — this is not coerced to "
            "a plausible substitute."
        )

    if site_preference in supported:
        # The compatibility path: TIDMAD's shipped concrete dtypes survive
        # untouched, which is what makes baseline A6 pass unmodified.
        return RUNTIME_SUPPORTED_DTYPES[site_preference]

    # §24.9 Q7 — the site's historical preference is not admissible for this
    # model, so fall through to the contract's canonical representation
    # (`admissible[0]`, filtered to what the runtime supports). Deterministic,
    # and it is `fcnet` that takes this path in production.
    return RUNTIME_SUPPORTED_DTYPES[supported[0]]


def resolve_contract_input_dtype(admissibility: DtypeAdmissibility) -> torch.dtype:
    """Choose one declared, supported model input dtype for a composed run.

    The declaration's first supported entry is canonical. Unlike a site's
    legacy preference, it cannot differ between training and inference.
    """
    return resolve_model_input_dtype(
        admissibility,
        site_preference=admissibility.admissible[0],
    )


def model_input_admissibility(
    model_type: str,
    task_contract: ModelIOContract,
) -> DtypeAdmissibility:
    """What THIS model's input boundary accepts.

    Precedence, mirroring ``plugin_loader.get_output_type``'s
    builtin-then-registry lookup:

    1. the model's OWN declaration, when it has one
       (``BUILTIN_INPUT_DTYPES``) — a model whose requirement genuinely
       differs from the task's;
    2. otherwise the **task's Model-I/O contract**, which is the declaration
       rendered to the LLM and therefore the requirement any model built for
       this task is expected to meet.

    Not two authorities: one lookup with a documented precedence, and the
    task contract is the answer for every model that does not override it.
    Today exactly one builtin overrides — ``fcnet``, the legacy autoencoder
    arm (§8c).
    """
    from ml_models.models_sandbox import BUILTIN_INPUT_DTYPES

    declared = BUILTIN_INPUT_DTYPES.get(model_type)
    if declared is not None:
        return declared
    return task_contract.input.dtype


def resolve_input_dtype(
    model_type: str,
    task_contract: ModelIOContract | None,
    *,
    site_preference: str,
) -> torch.dtype:
    """The single entry point the execution sites call.

    Replaces ``input_seq.float() if model_cfg.model_type == "fcnet" else
    input_seq.int()`` at all three input-dtype sites. Nothing here reads a
    model NAME to decide a dtype: the name is a key into a DECLARATION, in
    the same sense that ``get_target_torch_dtype`` keys a loss name into
    ``LOSS_TARGET_DTYPE_REGISTRY``.

    A bound task contract selects one canonical supported representation for
    every site. The site preference is used only for the pre-contract
    compatibility path below.

    ``task_contract is None`` is the **Regime-A adapter** for a caller that
    predates the contract — a direct ``run_experiment`` call in a test, or an
    argv without ``--model_io_json``. It resolves the model's OWN declaration
    when it has one (so ``fcnet`` still gets float32 with no contract in
    sight) and otherwise honours the site's historical dtype. It does NOT
    fabricate a TIDMAD contract, which would be the silent fallback §21
    forbids.
    """
    if task_contract is not None:
        return resolve_contract_input_dtype(model_input_admissibility(model_type, task_contract))

    from ml_models.models_sandbox import BUILTIN_INPUT_DTYPES

    declared = BUILTIN_INPUT_DTYPES.get(model_type)
    if declared is not None:
        return resolve_model_input_dtype(declared, site_preference=site_preference)
    return RUNTIME_SUPPORTED_DTYPES[site_preference]


class ContractCardinalityConflictError(RuntimeError):
    """A model config declares a class count the contract contradicts.

    §4b keeps ONE cardinality authority: the Dataset Profile's
    ``ValueEncoding.num_classes``, which the contract's class axis is
    cross-validated against at load time. A config that disagrees is not
    silently overwritten and does not silently win — either would make the
    config a second, independently configurable class count.
    """


def apply_contract_cardinality(
    config_data: dict,
    task_contract: ModelIOContract | None,
) -> dict:
    """Inject the contract's class cardinality into a model config payload.

    Returns a NEW mapping; the caller's dict is not mutated.

    * no contract, or a contract whose output carries no class axis — the
      payload is returned unchanged. Regime A, and the §4b case where
      cardinality is *not meaningful* for the output semantic;
    * a payload that does not mention ``num_classes`` — the derived value is
      injected, which is the normal path;
    * a payload that declares a CONTRADICTING value — typed failure. This is
      §4b's *"derive or explicitly cross-validate"*, and it is why the field
      on ``BaseConfig`` is not a second authority.
    """
    if task_contract is None:
        return dict(config_data)
    derived = task_contract.class_cardinality
    if derived is None:
        return dict(config_data)

    declared = config_data.get("num_classes")
    if declared is not None and declared != derived:
        raise ContractCardinalityConflictError(
            f"model config declares num_classes={declared} but the Model-I/O "
            f"contract derives {derived} from its class axis (itself "
            "cross-validated against the Dataset Profile). The contract is the "
            "authority; neither value is silently adopted."
        )

    resolved = dict(config_data)
    resolved["num_classes"] = derived
    return resolved
