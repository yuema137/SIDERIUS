"""Closed, inert catalog of audited native request/protocol boundaries.

Strings identify owners; they are never dynamically imported or executed.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True)
class CapabilityContract:
    input: str
    output: str


@dataclass(frozen=True)
class ArgumentContract:
    name: str
    contract: str
    required: bool = True


@dataclass(frozen=True)
class ProtocolContract:
    owner: str
    output: str
    arguments: tuple[ArgumentContract, ...]


@dataclass(frozen=True)
class ProtectedField:
    """One framework-owned location inside a custom-adaptor output contract.

    ``path`` is dotted; ``[]`` addresses every list element. ``unset`` requires
    the author to leave the value absent/None/empty, ``stamp-source`` additionally
    lets the framework write the adaptor provenance label there, and
    ``forbid-value`` refuses exactly ``value``.
    """

    path: str
    rule: Literal["unset", "stamp-source", "forbid-value"]
    value: str | None = None


CONTRACTS = MappingProxyType(
    {
        "interpretation.input": "agent.schemas.interpretation.InterpretationInput",
        "interpretation.output": "agent.schemas.interpretation.InterpretationOutput",
        "optional.text": "str | None",
        "optional.expert-advice": "agent.schemas.hyperparam_tuning.ExpertAdviceInput | None",
        "optional.expert-context": "list[agent.schemas.proposal.ExpertContextItem] | None",
        "optional.parameter-rules": "agent.schemas.parameter_rules.ParameterRules | None",
        "literature.input": "agent.schemas.literature_review.LiteratureReviewInput",
        "literature.output": "agent.schemas.literature_review.LiteratureReviewOutput",
        "literature.collection": (
            "list[agent.schemas.protocols.ml_literature_review_to_ml_model_propose"
            ".NamedLiteratureReviewOutput]"
        ),
        "proposal.input": "agent.schemas.proposal.ProposalInput",
        "proposal.output": "agent.schemas.proposal.ProposalOutput",
        "implementation.input": "agent.schemas.implementor.ImplementorInput",
        "implementation.output": "agent.schemas.implementor.ImplementorOutput",
        "validation.input": "agent.schemas.validator.ValidatorInput",
        "validation.output": "agent.schemas.validator.ValidatorOutput",
        "tuning.input": "agent.schemas.hyperparam_tuning.HyperparamTuningInput",
        "tuning.output": "agent.schemas.hyperparam_tuning.HyperparamTuningOutput",
        "native-training.settings": "workflows.candidate_training_settings.CandidateTrainingSettings",
        "storage": "agent.schemas.storage.StorageConfig",
        "optional.constraint-context": "agent.schemas.constraint_disclosure.ConstraintContext | None",
        "optional.task-composition-ref": "agent.schemas.hyperparam_tuning.TaskCompositionRef | None",
        "llm-provider": "Literal['gemini', 'openai', 'deepseek', 'anthropic', 'moonshot', 'zai']",
        "optional.model-id": "str | None",
    }
)

CAPABILITIES = MappingProxyType(
    {
        "interpretation": CapabilityContract("interpretation.input", "interpretation.output"),
        "literature": CapabilityContract("literature.input", "literature.output"),
        "proposal": CapabilityContract("proposal.input", "proposal.output"),
        "implementation": CapabilityContract("implementation.input", "implementation.output"),
        "tuning": CapabilityContract("tuning.input", "tuning.output"),
        "validation": CapabilityContract("validation.input", "validation.output"),
    }
)

PROTOCOLS = MappingProxyType(
    {
        "interpretation-to-proposal": ProtocolContract(
            "agent.schemas.protocols.ml_result_interp_to_ml_model_propose.local_full_context",
            "proposal.input",
            (
                ArgumentContract("output", "interpretation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("data_dir", "optional.text", False),
                ArgumentContract("task_composition_ref", "optional.task-composition-ref", False),
                ArgumentContract("human_advice", "optional.expert-advice", False),
                ArgumentContract("expert_context", "optional.expert-context", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
                ArgumentContract("workflow_parameter_rules", "optional.parameter-rules", False),
            ),
        ),
        "literature-to-proposal": ProtocolContract(
            "agent.schemas.protocols.ml_literature_review_to_ml_model_propose.local_typed_evidence",
            "proposal.input",
            (
                ArgumentContract("output", "literature.output"),
                ArgumentContract("proposal_input", "proposal.input"),
            ),
        ),
        "literature-collection-to-proposal": ProtocolContract(
            "agent.schemas.protocols.ml_literature_review_to_ml_model_propose"
            ".local_typed_evidence_many",
            "proposal.input",
            (
                ArgumentContract("reviews", "literature.collection"),
                ArgumentContract("proposal_input", "proposal.input"),
            ),
        ),
        "validated-candidate-to-tuning": ProtocolContract(
            "tools.candidate_worker.training.prepare_tuning_request",
            "tuning.input",
            (
                ArgumentContract("validation", "validation.output"),
                ArgumentContract("proposal", "proposal.output"),
                ArgumentContract("settings", "native-training.settings"),
            ),
        ),
        "proposal-to-implementation": ProtocolContract(
            "agent.schemas.protocols.ml_model_propose_to_ml_model_impl.local_full_spec",
            "implementation.input",
            (
                ArgumentContract("output", "proposal.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
                ArgumentContract("task_composition_ref", "optional.task-composition-ref", False),
            ),
        ),
        "proposed-implementation-to-validation": ProtocolContract(
            "workflows.candidate_validation_join.proposed_implementation_to_validation",
            "validation.input",
            (
                ArgumentContract("proposal", "proposal.output"),
                ArgumentContract("implementation", "implementation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("llm_provider", "llm-provider", False),
                ArgumentContract("llm_model_id", "optional.model-id", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
            ),
        ),
        "implementation-to-validation": ProtocolContract(
            "agent.schemas.protocols.ml_model_impl_to_ml_model_valid.local_all_fields",
            "validation.input",
            (
                ArgumentContract("output", "implementation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("llm_provider", "llm-provider", False),
                ArgumentContract("llm_model_id", "optional.model-id", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
            ),
        ),
    }
)

#: Contracts a custom adaptor COMBINE may emit (operator decision B6-D3 = B).
#: Authority contracts (validation, tuning, interpretation), capability inputs,
#: storage, constraints, parameter rules and task references are never
#: emittable. Widening this set is a reviewed catalog change.
CUSTOM_EMITTABLE = frozenset(
    {
        "optional.expert-context",
        "optional.expert-advice",
        "optional.text",
        "proposal.output",
        "literature.output",
    }
)


def _context_item_rules(prefix: str) -> tuple[ProtectedField, ...]:
    """`ExpertContextItem`: framework-stamped producer; never human or chain-mode findings."""
    return (
        ProtectedField(f"{prefix}source", "stamp-source"),
        ProtectedField(f"{prefix}kind", "forbid-value", "human"),
        ProtectedField(f"{prefix}kind", "forbid-value", "findings"),
    )


def _vocab_entry_rules(prefix: str) -> tuple[ProtectedField, ...]:
    """`VocabEntry`: external origin, no run attribution, never canonical."""
    return (
        ProtectedField(f"{prefix}origin", "stamp-source"),
        ProtectedField(f"{prefix}proposed_by_run", "unset"),
        ProtectedField(f"{prefix}seen_in_runs", "unset"),
        ProtectedField(f"{prefix}tier", "forbid-value", "canonical"),
    )


#: Framework-owned fields of every emittable contract. The author leaves them
#: unset; the framework stamps provenance after validation. Any other value is
#: refused, never silently replaced.
PROTECTED_FIELDS = MappingProxyType(
    {
        "optional.expert-context": _context_item_rules("[]."),
        "optional.expert-advice": (),
        "optional.text": (),
        "proposal.output": (
            ProtectedField("candidate_id", "unset"),
            ProtectedField("observed_prediction_reference", "unset"),
            ProtectedField("preflight_estimated_minutes", "unset"),
            ProtectedField("preflight_factor", "unset"),
            *_vocab_entry_rules("proposed_discoveries[]."),
        ),
        "literature.output": (
            ProtectedField("agent_card.agent_name", "stamp-source"),
            ProtectedField("agent_card.trust_level", "forbid-value", "hard_limit"),
            ProtectedField("run_name", "stamp-source"),
            *_context_item_rules("findings[]."),
            *_vocab_entry_rules("new_vocab_candidates[]."),
            ProtectedField("search_decisions", "unset"),
        ),
    }
)


@dataclass(frozen=True)
class RankableField:
    """A non-metric numeric field on the entries of a catalogued list.

    ``provenance`` labels where the number comes from; it is recorded beside every
    ranking built from it and is never a score or a validity fact.
    """

    list_field: str
    item_field: str
    provenance: str


# Element contract -> the catalogued contract of its ``collect/v1`` collection. A
# collection is the ordered named list its consumer protocol reads, one entry per
# admissible input with ``contribution_id`` = the source node id (B6-4).
COLLECTION_CONTRACTS = MappingProxyType({"literature.output": "literature.collection"})

# Contract -> its one list field that adaptors may concatenate or split.
SPLITTABLE_ITEMS = MappingProxyType({"literature.output": "findings"})

# Contract -> the catalogued entry field that ``field-rank/v1`` may rank by.
RANKABLE_FIELDS = MappingProxyType(
    {"literature.output": RankableField("findings", "confidence", "self-reported")}
)


@dataclass(frozen=True)
class AdaptorStrategyContract:
    """One closed, versioned adaptor strategy kind: its stage, declaration and owner."""

    stage: Literal["combine", "select", "distribute"]
    declaration: str
    owner: str


_STRATEGY_MODELS = "workflows.definition.adaptor_strategies"
_COMBINE_OWNER = "workflows.adaptors.combine.combine"
_SELECT_OWNER = "workflows.adaptors.select.select"
_DISTRIBUTE_OWNER = "workflows.adaptors.run.run_deterministic_adaptor"
_LLM_MODELS = "workflows.definition.llm_strategies"
_LLM_OWNER = "workflows.judge_strategies.run_llm_strategy"

# Closed set of adaptor strategy kinds (B6). ``collect/v1`` is admitted only over an
# element contract with a ``COLLECTION_CONTRACTS`` entry and its consumer protocol
# (``literature.output`` since B6-4; ``tuning.output`` waits for B6-9). The kind
# string carries its version; a changed semantic is a new row. LLM kinds (B2) are
# owned by ``workflows.judge_strategies`` and execute only under
# ``native-literature-judged/v1`` (B6-8a).
ADAPTOR_STRATEGIES = MappingProxyType(
    {
        "pass/v1": AdaptorStrategyContract(
            "combine", f"{_STRATEGY_MODELS}.PassCombine", _COMBINE_OWNER
        ),
        "collect/v1": AdaptorStrategyContract(
            "combine", f"{_STRATEGY_MODELS}.CollectCombine", _COMBINE_OWNER
        ),
        "concat-items/v1": AdaptorStrategyContract(
            "combine", f"{_STRATEGY_MODELS}.ConcatItemsCombine", _COMBINE_OWNER
        ),
        "metric-rank/v1": AdaptorStrategyContract(
            "combine", f"{_STRATEGY_MODELS}.MetricRankCombine", _COMBINE_OWNER
        ),
        "field-rank/v1": AdaptorStrategyContract(
            "combine", f"{_STRATEGY_MODELS}.FieldRankCombine", _COMBINE_OWNER
        ),
        "debate-judge/v1": AdaptorStrategyContract(
            "combine", f"{_LLM_MODELS}.DebateJudgeStrategy", _LLM_OWNER
        ),
        "rubric-rank/v1": AdaptorStrategyContract(
            "combine", f"{_LLM_MODELS}.RubricRankStrategy", _LLM_OWNER
        ),
        "primary-advisors-llm/v1": AdaptorStrategyContract(
            "combine", f"{_LLM_MODELS}.PrimaryAdvisorsStrategy", _LLM_OWNER
        ),
        "judge-merge/v1": AdaptorStrategyContract(
            "combine", f"{_LLM_MODELS}.JudgeMergeStrategy", _LLM_OWNER
        ),
        "all/v1": AdaptorStrategyContract("select", f"{_STRATEGY_MODELS}.AllSelect", _SELECT_OWNER),
        "first-admissible/v1": AdaptorStrategyContract(
            "select", f"{_STRATEGY_MODELS}.FirstAdmissibleSelect", _SELECT_OWNER
        ),
        "top-k/v1": AdaptorStrategyContract(
            "select", f"{_STRATEGY_MODELS}.TopKSelect", _SELECT_OWNER
        ),
        "threshold/v1": AdaptorStrategyContract(
            "select", f"{_STRATEGY_MODELS}.ThresholdSelect", _SELECT_OWNER
        ),
        "single/v1": AdaptorStrategyContract(
            "distribute", f"{_STRATEGY_MODELS}.SingleDistribute", _DISTRIBUTE_OWNER
        ),
        "per-item/v1": AdaptorStrategyContract(
            "distribute", f"{_STRATEGY_MODELS}.PerItemDistribute", _DISTRIBUTE_OWNER
        ),
        "split-items/v1": AdaptorStrategyContract(
            "distribute", f"{_STRATEGY_MODELS}.SplitItemsDistribute", _DISTRIBUTE_OWNER
        ),
        "replicate/v1": AdaptorStrategyContract(
            "distribute", f"{_STRATEGY_MODELS}.ReplicateDistribute", _DISTRIBUTE_OWNER
        ),
    }
)

# Contracts whose succeeded values carry formal metric results (Health-qualified
# admission; an LLM ranking may filter them, never reorder them).
METRIC_SCORED_CONTRACTS = frozenset({"tuning.output"})

# Contracts whose succeeded values carry a deterministic pass/fail validity flag.
VALIDITY_GATED_CONTRACTS = frozenset({"validation.output"})


@dataclass(frozen=True)
class RouteObservable:
    """One readable native output field, named ``module.Class.field``.

    This package never imports it; the runtime route projection reads only the
    final attribute name from the verified native record of ``contract``.
    """

    contract: str
    field: str
    kind: Literal["bool", "enum", "metric"]
    values: tuple[str, ...] = ()

    @property
    def attribute(self) -> str:
        """The native attribute name: the last segment of ``field``."""
        return self.field.rpartition(".")[2]


# Closed list of fields a route predicate may read. Adding one requires the
# native-schema drift test; predicates never name free fields or JSON paths.
ROUTE_OBSERVABLES = MappingProxyType(
    {
        "validation.passed": RouteObservable(
            "validation.output", "agent.schemas.validator.ValidatorOutput.passed", "bool"
        ),
        "tuning.status": RouteObservable(
            "tuning.output",
            "agent.schemas.hyperparam_tuning.HyperparamTuningOutput.status",
            "enum",
            ("completed", "partial", "failed"),
        ),
        "tuning.valid_formal": RouteObservable(
            "tuning.output",
            "agent.schemas.hyperparam_tuning.HyperparamTuningOutput"
            ".best_valid_formal_denoising_score",
            "metric",
        ),
    }
)
