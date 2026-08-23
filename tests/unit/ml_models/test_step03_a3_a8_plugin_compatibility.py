"""Step 03 Checkpoint 0 — baselines **A3** and **A8**: plugin compatibility.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§5 (A3 and A8 — "capture first"), §8b (``output_type`` becomes a derived
projection), §15 (Checkpoint 0), §21, §24.3.

Both baselines guard the same migration — §8b collapses ``output_type``
from three competing surfaces to one projection — but they guard opposite
failure directions, so they share a module and nothing else.

**Zero production diff.** Neither baseline changes behaviour; both pin it.

---

**A3 — the two tolerance tiers, pinned as DISTINCT behaviours.**

``output_type`` is resolved at two points that disagree about strictness:

===========================  =========================  ==================
tier                         site                       on a bad input
===========================  =========================  ==================
load-time declaration        ``plugin_loader.py:81-88`` warn, default to
                                                        ``"classifier"``
lookup-time resolution       ``plugin_loader.py:192``   raise
                                                        ``UnknownOutput-
                                                        ContractError``
===========================  =========================  ==================

§5 A3 is explicit that this divergence is **pre-existing and NOT Step
03's to unify**. That makes the *divergence itself* the thing to pin: a
§8b projection is a natural place to accidentally harmonise them, in
either direction, and either harmonisation is a behaviour change wearing
a refactor's clothes.

**AMENDED by Step 12 / PR-12a C4 (issue #234), deliberately and with
operator ratification.** A3 pinned the leniency so it could not change by
accident; #234 is the decision to change it on purpose. The load-time tier
now splits what it used to treat alike:

===============================  ==================================
declaration                      load-time behaviour
===============================  ==================================
ABSENT                           still defaults to ``"classifier"``
                                 (the pre-declaration compat path,
                                 unchanged — and the validator's twin
                                 ``_DEFAULT_OUTPUT_TYPE`` has its own
                                 reachability test)
PRESENT but not plugin-legal     **REFUSES** — named reason, ``None``
                                 return, never coerced
===============================  ==================================

The reason is the graduation falsifier: an external package's model that
emits segmentation masks must not train, score and rank as a 256-class
classifier because its metadata was rewritten. The tiers still differ —
the lenient tier is now lenient about OMISSION only — and that remaining
divergence is what the A3 tests below pin. New owner of the strictness
half: ``test_step12_pr12a_c4_output_type_vocabulary.py``.

The unique failure class: *the lenient tier silently becomes strict, or
the strict tier silently becomes lenient.* The strict tier alone is
already covered — ``test_unknown_output_contract_fails_closed.py``,
``test_unknown_contract_consumer_reachability.py`` and
``test_registry_population_is_self_healing.py:190``. What no test covers
is the **lenient** tier's defaulting, and nothing at all asserts that the
two tiers differ. ``test_plugin_loader.py`` pins missing
``PLUGIN_MODEL_TYPE`` / ``PLUGIN_CONFIG_CLASS`` / syntax errors, but never
``PLUGIN_OUTPUT_TYPE``.

---

**A8 — prior on-disk generated plugins stay loadable.**

§5 A8 accepts either evidence: the plugins still load and register, **or**
a declared and accepted workspace boundary. Both are honest outcomes and
this module reports which one it observed, because
``agent_generated/models/*`` is **gitignored** (only ``.gitkeep`` is
tracked). A developer checkout holds real accumulated plugins; a fresh
clone and CI hold none. A test that assumed either would be wrong half
the time, so the workspace is inspected and the boundary declared —
never silently skipped past.
"""

from __future__ import annotations

import textwrap

import pytest

import ml_models.plugin_loader as pl
from ml_models.plugin_loader import UnknownOutputContractError

# ---------------------------------------------------------------------------
# A3 — plugin source variants. Identical except for the declaration under
# test, so the observed difference can only come from that declaration.
# ---------------------------------------------------------------------------

_PLUGIN_TEMPLATE = textwrap.dedent("""\
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "{name}"
    {output_type_line}

    class Cfg(BaseModel):
        model_type: str = "{name}"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class Mdl(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.proj = nn.Linear(config.segmentation_size, config.segmentation_size)

        def forward(self, x):
            return self.proj(x.float()).unsqueeze(1).expand(-1, 256, -1)

    PLUGIN_CONFIG_CLASS = Cfg
    PLUGIN_MODEL_CLASS = Mdl
""")


def _write_plugin(tmp_path, name: str, output_type_line: str) -> str:
    path = tmp_path / f"{name}.py"
    path.write_text(_PLUGIN_TEMPLATE.format(name=name, output_type_line=output_type_line))
    return str(path)


class TestA3LoadTimeTierIsLenient:
    """Tier 1: a bad or absent declaration DEFAULTS, and never fails."""

    def test_absent_declaration_defaults_to_classifier(self, tmp_path):
        """``PLUGIN_OUTPUT_TYPE`` is optional — the backward-compat path for
        every plugin generated before the declaration existed."""
        spec = pl._load_plugin(_write_plugin(tmp_path, "a3_absent", ""))
        assert spec is not None
        assert spec["output_type"] == "classifier"

    def test_invalid_declaration_now_REFUSES(self, tmp_path, capsys):
        """UPGRADED by Step 12 / PR-12a C4 (issue #234) — same failure class,
        reversed expectation.

        A3 pinned this as "warns and defaults to classifier" so the leniency
        could not change by ACCIDENT. #234 changed it on PURPOSE: an
        unrecognised declaration is a defect, and coercing it turned a
        metadata defect into wrong science. The trace requirement A3 cared
        about is stronger now, not weaker — the reason is named and the
        plugin does not load at all.
        """
        spec = pl._load_plugin(
            _write_plugin(tmp_path, "a3_invalid", 'PLUGIN_OUTPUT_TYPE = "banana"')
        )
        assert spec is None
        out = capsys.readouterr().out
        assert "banana" in out
        assert "a3_invalid" in out
        assert "is not a legal plugin output contract" in out

    @pytest.mark.parametrize("declared", ["classifier", "regressor"])
    def test_each_declared_value_is_carried_through_verbatim(self, tmp_path, declared):
        """The alphabet a PLUGIN may declare (``PLUGIN_LEGAL_OUTPUT_TYPES``).

        NARROWED by Step 12 / PR-12a C4. ``hybrid`` was included here because
        "the loader's hybrid arm must not be dropped just because no generated
        plugin reaches it today" — and the audit confirmed that literally:
        across the 109 generated plugins on record, ZERO declare it. It is a
        BUILTIN adapter value (``BUILTIN_OUTPUT_TYPES["fcnet"]``), so it stays
        in ``OUTPUT_TYPE_VOCABULARY`` and leaves the plugin-legal subset. A3's
        concern — that the hybrid arm not be silently dropped — is now owned by
        ``test_step12_pr12a_c4_output_type_vocabulary.TestHybridStaysLoadBearingForBuiltins``,
        which pins the builtin table, ``get_output_type`` AND the real
        consumer branch in the inference child.
        """
        spec = pl._load_plugin(
            _write_plugin(tmp_path, f"a3_{declared}", f'PLUGIN_OUTPUT_TYPE = "{declared}"')
        )
        assert spec is not None
        assert spec["output_type"] == declared


class TestA3LookupTimeTierIsStrict:
    """Tier 2: an unregistered model FAILS CLOSED — there is no default."""

    def test_unregistered_model_raises(self):
        with pytest.raises(UnknownOutputContractError):
            pl.get_output_type("a3_never_registered_anywhere")


class TestA3TheTwoTiersDiverge:
    """The divergence itself, asserted as one claim.

    This is the assertion §5 A3 actually asks for, and the one no existing
    test makes. It reds if a §8b projection harmonises the tiers in EITHER
    direction — which is a behaviour change requiring an operator decision,
    not a tidy-up Step 03 may perform in passing.
    """

    def test_an_OMITTED_declaration_defaults_while_a_bad_lookup_raises(self, tmp_path):
        """UPGRADED by Step 12 / PR-12a C4 — the divergence still exists, and
        it MOVED. This test's job is unchanged: prove the two tiers are not
        accidentally harmonised.

        A3 demonstrated the divergence with a BAD declaration, which #234 has
        since made strict on purpose. The lenient tier is now lenient about
        OMISSION only, so the demonstration uses omission. Both halves are
        asserted, as before, because a test that only checked one would go
        green if the other quietly moved to match it.
        """
        lenient = pl._load_plugin(_write_plugin(tmp_path, "a3_divergence", ""))
        assert lenient is not None
        assert lenient["output_type"] == "classifier", (
            "the load-time tier became strict about OMISSION — it must still "
            "default, or every pre-declaration plugin stops loading"
        )

        with pytest.raises(UnknownOutputContractError):
            pl.get_output_type("a3_divergence")

    def test_loading_a_plugin_does_not_by_itself_register_it(self, tmp_path):
        """Why the two tiers can disagree at all: ``_load_plugin`` returns a
        spec, it does not populate ``PLUGIN_OUTPUT_TYPE_REGISTRY``. Pinned
        because a projection that registered as a side effect of loading
        would erase the divergence without touching either tier's code."""
        name = "a3_load_without_register"
        assert name not in pl.PLUGIN_OUTPUT_TYPE_REGISTRY
        spec = pl._load_plugin(_write_plugin(tmp_path, name, 'PLUGIN_OUTPUT_TYPE = "regressor"'))
        assert spec is not None
        assert name not in pl.PLUGIN_OUTPUT_TYPE_REGISTRY


# ---------------------------------------------------------------------------
# A8 — prior on-disk generated plugins
# ---------------------------------------------------------------------------


def _on_disk_plugin_files() -> list[str]:
    """Every ``.py`` the production loader would actually scan."""
    import os

    found: list[str] = []
    for d in pl._resolve_plugin_dirs():
        if not os.path.isdir(d):
            continue
        found += [
            os.path.join(d, f)
            for f in sorted(os.listdir(d))
            if f.endswith(".py") and not f.startswith("_")
        ]
    return found


class TestA8PriorPluginsRemainLoadable:
    """The pre-existing plugin population, through the production loader."""

    def test_every_on_disk_plugin_still_loads_and_declares_a_valid_contract(self):
        """The real A8 claim: Step 03 must not break the existing population.

        Skips with an explicit reason when the workspace has no plugins —
        the declared boundary — rather than passing vacuously.
        """
        files = _on_disk_plugin_files()
        if not files:
            pytest.skip(
                "A8 workspace boundary: no on-disk generated plugins in "
                f"{pl._resolve_plugin_dirs()}. agent_generated/models/* is "
                "gitignored, so a fresh clone or CI has none. This is the "
                "declared boundary of §5 A8, not a silent pass."
            )

        failed: list[str] = []
        contracts: dict[str, str] = {}
        for path in files:
            spec = pl._load_plugin(path)
            if spec is None:
                failed.append(path)
                continue
            contracts[spec["model_type"]] = spec["output_type"]

        assert not failed, f"{len(failed)} previously-loadable plugin(s) stopped loading: {failed}"
        assert set(contracts.values()) <= {"classifier", "regressor", "hybrid"}
        assert contracts, "plugins were found on disk but none produced a contract"
