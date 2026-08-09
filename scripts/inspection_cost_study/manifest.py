"""V21 PR F — deterministic study manifest (design §0.C/§0.D).

TIMING-BLIND by construction (operator rule): entries derive only from
config-schema validity, the frozen per-architecture ladders, and
instantiability. Nothing here observes a clock, and invalid configs stay
in the manifest as evidence.

Population A uses the REAL plugin loader as the loadability authority
(`preload_global_models`), never filename globbing alone. Population B
scales each built-in through its OWN schema knobs (§0.C table); no
architecture is forced onto a common parameter grid.
"""

from __future__ import annotations

from typing import Any, Literal

from scripts.inspection_cost_study.schemas import Population, SweepEntry

#: The frozen per-architecture ladders (design §0.C). One PRIMARY knob
#: (or knob group) per family, multiplied through a deterministic ladder;
#: every exact config lands in the manifest verbatim.
_LADDER: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)

#: fcnet's default IS the ~323 M reference, so its ladder descends.
_FCNET_LADDER: tuple[float, ...] = (0.125, 0.25, 0.5, 1.0)


def _scaled(base: int, mult: float, *, minimum: int = 1) -> int:
    return max(minimum, round(base * mult))


def _builtin_grid() -> list[tuple[str, dict[str, Any]]]:
    """(model_type, model_cfg overrides) — deterministic, timing-blind."""
    grid: list[tuple[str, dict[str, Any]]] = []
    for m in _LADDER:
        grid.append(
            (
                "wavenet",
                {
                    "residual_channels": _scaled(32, m),
                    "gate_channels": _scaled(64, m),
                    "skip_channels": _scaled(32, m),
                },
            )
        )
        grid.append(("punet", {"multi": _scaled(40, m)}))
        grid.append(
            (
                "transformer",
                {
                    # embedding_dim stays divisible by nhead=4 for every
                    # ladder step (32 * {0.5..8} ∈ {16..256}).
                    "embedding_dim": _scaled(32, m, minimum=4),
                    "dim_feedforward": _scaled(128, m),
                },
            )
        )
        grid.append(
            (
                "rnn",
                {
                    "embedding_dim": _scaled(128, m),
                    "hidden_dim": _scaled(256, m),
                },
            )
        )
        grid.append(("gated_fno", {"width": _scaled(64, m)}))
    for m in _FCNET_LADDER:
        grid.append(
            (
                "fcnet",
                {"latent_dims": [_scaled(4000, m), _scaled(400, m), 40]},
            )
        )
    return grid


def _loss_for(model_type: str) -> Literal["ce", "smooth_l1"]:
    """The loss family production would pair with this model's contract."""
    from ml_models.plugin_loader import get_output_type

    return "smooth_l1" if get_output_type(model_type) == "regressor" else "ce"


def _instantiate(model_type: str, model_cfg: dict[str, Any], loss_type: str):
    """Build via the REAL production path (`_build_model`)."""
    from agent.skills.evaluate_vram_skill.wrapper import _build_model

    return _build_model(model_type, model_cfg, loss_type)


def _entry(
    entry_id: str,
    population: Population,
    family: str,
    model_type: str,
    model_cfg: dict[str, Any],
) -> SweepEntry:
    loss_type = "ce"
    try:
        loss_type = _loss_for(model_type)
        model = _instantiate(model_type, model_cfg, loss_type)
        total = sum(p.numel() for p in model.parameters())
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        cfg_obj = getattr(model, "config", None)
        seg = int(getattr(cfg_obj, "segmentation_size", 0) or 0)
        if seg <= 0:
            # The config object is the authority; fall back to re-building it.
            from ml_models.models_format_sandbox import get_config_class

            cfg_cls = get_config_class(model_type)
            if cfg_cls is None:
                raise ValueError(f"no config class registered for {model_type!r}")
            seg = int(cfg_cls(**model_cfg).segmentation_size)
        del model
        return SweepEntry(
            entry_id=entry_id,
            population=population,
            architecture_family=family,
            model_identity=model_type,
            exact_config=dict(model_cfg),
            segmentation_size=seg,
            realized_total_parameter_count=total,
            realized_trainable_parameter_count=trainable,
            loss_type=loss_type,
        )
    except Exception as exc:
        return SweepEntry(
            entry_id=entry_id,
            population=population,
            architecture_family=family,
            model_identity=model_type,
            exact_config=dict(model_cfg),
            segmentation_size=1,
            loss_type=loss_type,
            load_error=f"{type(exc).__name__}: {exc}"[:500],
        )


def build_manifest() -> list[SweepEntry]:
    """The full deterministic manifest: population A then population B.

    Ordering is deterministic by construction (sorted loader output; the
    fixed ladder order), so the content hash is stable with no seed
    needed for the manifest itself.
    """
    from ml_models.plugin_loader import preload_global_models

    entries: list[SweepEntry] = []

    # Population A — the loader is the authority (sorted file order).
    for model_type in preload_global_models():
        entries.append(
            _entry(
                entry_id=f"A_{model_type}",
                population="v20_generated_realized",
                family="generated",
                model_type=model_type,
                model_cfg={},
            )
        )

    # Population B — the frozen ladders.
    for idx, (model_type, overrides) in enumerate(_builtin_grid()):
        entries.append(
            _entry(
                entry_id=f"B_{idx:03d}_{model_type}",
                population="builtin_reference",
                family=model_type,
                model_type=model_type,
                model_cfg=overrides,
            )
        )
    return entries


#: P6.3's ledger-recorded trained counts (overlay anchors, Q-F-1).
_P63_VALUES: tuple[int, ...] = (663_488, 7_280_256, 8_409_280, 12_772_096)


def select_pilot(entries: list[SweepEntry]) -> list[SweepEntry]:
    """The deterministic 12-entry pilot (design F2a §3) — timing-blind.

    Ramp order: the two size extremes FIRST (by realized total), then the
    incident-class deep dilated architecture, then the four population-A
    entries nearest each P6.3 recorded value, then fcnet at its ~323 M
    default plus the largest VALID ladder entry of three reference
    families. Selection reads only manifest facts, never timings.
    """
    loadable = [e for e in entries if e.load_error is None]
    a = [e for e in loadable if e.population == "v20_generated_realized"]
    b = [e for e in loadable if e.population == "builtin_reference"]

    def total(e: SweepEntry) -> int:
        return e.realized_total_parameter_count or 0

    picked: list[SweepEntry] = []

    def add(e: SweepEntry | None) -> None:
        if e is not None and all(x.entry_id != e.entry_id for x in picked):
            picked.append(e)

    smallest = min(loadable, key=lambda e: (total(e), e.entry_id))
    largest = max(loadable, key=lambda e: (total(e), e.entry_id))
    add(smallest)
    add(largest)
    # The incident class: the deep dilated V20 baseline, by exact identity.
    add(next((e for e in a if e.model_identity == "wavenet_30layer_baseline"), None))
    for target in _P63_VALUES:
        add(min(a, key=lambda e: (abs(total(e) - target), e.entry_id)))
    # fcnet at its default (~323 M) = the fcnet ladder's largest valid entry.
    fc = [e for e in b if e.architecture_family == "fcnet"]
    add(max(fc, key=lambda e: (total(e), e.entry_id)) if fc else None)
    for family in ("wavenet", "transformer", "rnn"):
        fam = [e for e in b if e.architecture_family == family]
        add(max(fam, key=lambda e: (total(e), e.entry_id)) if fam else None)
    # Deterministic pad to exactly 12 from the largest remaining entries.
    for e in sorted(loadable, key=lambda e: (-total(e), e.entry_id)):
        if len(picked) >= 12:
            break
        add(e)
    return picked[:12]
