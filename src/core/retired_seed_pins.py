"""Refusal and migration of the retired per-purpose seed pins (issue #983 T13).

Contract: ``docs/agent-reference/mechanisms/seeding.md#retired-seed-pins``.

``sampling_seed`` and ``train_base_seed`` once pinned one tuner seed for every
attempt of a run. Every seed now derives from ``run_seed``, so an input that
still carries a pin is refused rather than silently ignored. The one migration
is for documents recorded before the retirement that merely projected the pins
as ``null``: a reviewed launch projection drops a ``null`` pin and refuses a set
one, so a seedless saved review stays comparable and readable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

RETIRED_SEED_PINS: Final = ("sampling_seed", "train_base_seed")
_MESSAGE: Final = "seeds derive from run_seed; set --run_seed"


class RetiredSeedPin(ValueError):
    """An input still carries a retired per-purpose seed pin."""


def retired_pin_message(where: str, names: list[str]) -> str:
    return f"{where} carries retired seed pin(s) {names}: {_MESSAGE}"


def refuse_retired_seed_pins(values: object, where: str) -> None:
    """Raise :class:`RetiredSeedPin` when a raw mapping names any retired pin."""
    if not isinstance(values, Mapping):
        return
    present = sorted(name for name in RETIRED_SEED_PINS if name in values)
    if present:
        raise RetiredSeedPin(retired_pin_message(where, present))


def migrate_reviewed_launch_settings[V](settings: Mapping[str, V]) -> dict[str, V]:
    """Drop ``null`` retired pins from a pre-retirement launch projection.

    A non-null pin was an executed treatment this build cannot reproduce, so
    it is refused with :class:`RetiredSeedPin` instead of being dropped.
    """
    set_pins = sorted(name for name in RETIRED_SEED_PINS if settings.get(name) is not None)
    if set_pins:
        raise RetiredSeedPin(retired_pin_message("the reviewed launch settings", set_pins))
    return {key: value for key, value in settings.items() if key not in RETIRED_SEED_PINS}
