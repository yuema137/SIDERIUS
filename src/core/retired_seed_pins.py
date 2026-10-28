"""Readback migration and refusal of the retired seed pins (issue #983 T13).

Contract: ``docs/agent-reference/mechanisms/seeding.md#retired-seed-pins``.

``sampling_seed`` and ``train_base_seed`` once pinned one tuner seed for every
attempt of a run. Every seed now derives from ``run_seed``. The rule has two
halves:

- **Readback.** Records written before the retirement stay readable. A
  ``null`` pin meant "no pin" and is dropped (:func:`split_retired_seed_pins`);
  a set pin is kept as historical provenance in the owning schema's
  ``retired_seed_pins`` field, never as an execution input.
- **Execution.** A launch or continuation that still carries a set pin is
  refused (:func:`refuse_set_pins`), and a launch argument naming a pin is
  refused outright.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

RetiredPinName = Literal["sampling_seed", "train_base_seed"]
RetiredSeedPins = dict[RetiredPinName, int]

RETIRED_SEED_PINS: Final[tuple[RetiredPinName, ...]] = ("sampling_seed", "train_base_seed")
_MESSAGE: Final = "seeds derive from run_seed; set --run_seed"


class RetiredSeedPin(ValueError):
    """An execution input still carries a retired per-purpose seed pin."""


def retired_pin_message(where: str, names: list[str]) -> str:
    return f"{where} carries retired seed pin(s) {names}: {_MESSAGE}"


def split_retired_seed_pins(data: object) -> object:
    """Pydantic ``mode="before"`` helper: move pins out of a raw mapping.

    ``null`` pins are dropped; set pins move to ``retired_seed_pins``. Any other
    input is returned unchanged.
    """
    if not isinstance(data, Mapping) or not any(name in data for name in RETIRED_SEED_PINS):
        return data
    kept = {key: value for key, value in data.items() if key not in RETIRED_SEED_PINS}
    set_pins = {name: data[name] for name in RETIRED_SEED_PINS if data.get(name) is not None}
    if set_pins:
        kept["retired_seed_pins"] = {**dict(data.get("retired_seed_pins") or {}), **set_pins}
    return kept


def refuse_set_pins(pins: RetiredSeedPins | None, where: str) -> None:
    """Refuse to execute or continue an input that recorded a set pin."""
    if pins:
        raise RetiredSeedPin(retired_pin_message(where, sorted(pins)))


def migrate_reviewed_launch_settings[V](settings: Mapping[str, V]) -> dict[str, V]:
    """Drop ``null`` retired pins from a pre-retirement launch projection.

    A non-null pin was an executed treatment this build cannot reproduce, so
    it is refused with :class:`RetiredSeedPin` instead of being dropped.
    """
    set_pins = sorted(name for name in RETIRED_SEED_PINS if settings.get(name) is not None)
    if set_pins:
        raise RetiredSeedPin(retired_pin_message("the reviewed launch settings", set_pins))
    return {key: value for key, value in settings.items() if key not in RETIRED_SEED_PINS}
