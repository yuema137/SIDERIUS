"""Pure deterministic adaptor strategy core (no execution wiring).

Contract: ``adaptor-contract.md`` beside this file.
"""

from .combine import CollectedEntry, CollectedItems, Combined, RankEntry, Ranking, Unit, combine
from .items import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorStrategyError,
    ItemAdmission,
    admit,
    admit_items,
)
from .record import AdaptorContribution, AdaptorRecord, OutputDigest, build_adaptor_record
from .run import AdaptorOutcome, AdaptorOutput, run_deterministic_adaptor
from .select import chosen_units, select

__all__ = [
    "AdaptorContribution",
    "AdaptorInputRef",
    "AdaptorItem",
    "AdaptorOutcome",
    "AdaptorOutput",
    "AdaptorRecord",
    "AdaptorStrategyError",
    "CollectedEntry",
    "CollectedItems",
    "Combined",
    "ItemAdmission",
    "OutputDigest",
    "RankEntry",
    "Ranking",
    "Unit",
    "admit",
    "admit_items",
    "build_adaptor_record",
    "chosen_units",
    "combine",
    "run_deterministic_adaptor",
    "select",
]
