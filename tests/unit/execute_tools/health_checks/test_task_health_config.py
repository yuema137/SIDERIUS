"""Step 08b C1 — the task-owned Health config document, Phase-A validation.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §3.1,
§3.7, §3.9, §4.1.

Defect classes owned here, none of which Pydantic, Pyright, Ruff or a Gate
can reach on its own:

* **Phase A silently becoming Phase B** — a schema that requires an external
  check/provider id to EXIST is unusable by definition, because the plugin
  that registers it has not loaded when the document is parsed. The
  positive-negative pair below is the executable statement that parsing and
  resolution are different questions with different answers.
* **A task restating framework policy** — a document that accepts
  ``on_fail`` or ``aggregation`` inside ``parameters`` creates a second copy
  of an operational field and therefore a precedence rule to get wrong. The
  rejection is what makes §3.7's single-source ownership structural.
* **The value unit drifting from the value factor** — 08a left
  ``value_scale_unit`` absent precisely because the millivolt NUMBER was a
  check-local literal owned by nothing. A document that lets the axis be
  declared independently of the factor reintroduces exactly that split.
* **A peek opt-in resolving to nothing** — an entry asking for the task's
  peek set when none is declared would fall back to a check's own default
  file source, quietly changing which files a gate watches.
* **A second production reader of task-owned truth** — the guard at the
  bottom. It began as C1's inertness assertion and was INVERTED at C2 into a
  seam allowlist rather than deleted, so the invariant survived the wiring
  that retired its original form.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from execute_tools.health_checks._task_health_config import (
    FRAMEWORK_OWNED_PARAMETER_KEYS,
    HealthDisposition,
    HealthPluginRef,
    HealthProviderBinding,
    HealthRosterEntry,
    TaskHealthConfig,
    ValueScale,
)
from execute_tools.health_checks.schemas import TaskHealthFacts

REPO_ROOT = Path(__file__).resolve().parents[4]
"""tests/unit/execute_tools/health_checks/<this file> → four hops to the root.

Derived from this file's location so the test reads the checkout it is being
executed from (CLAUDE.md portability rule) — and asserted below, because 08a
recorded an off-by-one here that ran ``git grep`` outside the repository and
let the same guard pass vacuously."""

PRODUCTION_PACKAGES = ("execute_tools", "nodes", "agent", "core", "scripts", "workflows")


def _tidmad_shaped_document() -> dict[str, object]:
    """A document in the shape C5 will migrate TIDMAD into.

    Values are the ones currently in ``configs/health_checks.yaml``; this is
    a SHAPE rehearsal, not the migration — C1 wires nothing.
    """
    return {
        "facts": {
            "encoding_family": "int8_symbol_stream",
            "symbol_cardinality": 256,
            "file_group_size": 20,
            "sampling_frequency_hz": 1.0e7,
        },
        "value_scale": {"unit": "mV", "units_per_sample": 40.0 / 128.0},
        "health_peek_files": [3, 10, 17],
        "plugins": [{"kind": "file", "ref": "./plugins/health.py"}],
        "providers": [{"provider_id": "tidmad.peek", "config": {"channel": "denoised"}}],
        "roster": [
            {
                "gate_id": "output_diversity_blocking",
                "check": "output_diversity",
                "disposition": "blocking",
                "parameters": {"min_unique_int8_values": 25, "peek_samples": 100000},
                "uses_health_peek_files": True,
                "reason": "FCNet floor=52 gives a 2.08x margin.",
            },
            {
                "gate_id": "per_file_output_std_recording",
                "check": "per_file_output_std",
                "disposition": "recording",
                "parameters": {"peek_samples": 100000},
            },
        ],
    }


class TestTidmadShapedDocumentParses:
    """The document the migration targets is expressible, with the values it must carry."""

    def test_parsed_values_equal_hardcoded_expectations(self):
        """Expectations are hardcoded, never read back from the parser.

        Asserting ``cfg.health_peek_files == cfg.health_peek_files`` — or
        against the same literal the fixture built — would pass for any
        parser, including one that dropped the field entirely.
        """
        cfg = TaskHealthConfig.model_validate(_tidmad_shaped_document())

        assert cfg.health_peek_files == (3, 10, 17)
        assert cfg.value_scale is not None
        assert cfg.value_scale.unit == "mV"
        assert cfg.value_scale.units_per_sample == 0.3125
        assert cfg.facts.encoding_family == "int8_symbol_stream"
        assert cfg.facts.symbol_cardinality == 256
        assert cfg.plugins == (HealthPluginRef(kind="file", ref="./plugins/health.py"),)
        assert cfg.providers[0].provider_id == "tidmad.peek"
        assert cfg.providers[0].config == {"channel": "denoised"}

        blocking, recording = cfg.roster
        assert blocking.gate_id == "output_diversity_blocking"
        assert blocking.check == "output_diversity"
        assert blocking.disposition is HealthDisposition.BLOCKING
        assert blocking.parameters == {"min_unique_int8_values": 25, "peek_samples": 100000}
        assert blocking.uses_health_peek_files is True
        assert recording.disposition is HealthDisposition.RECORDING
        assert recording.uses_health_peek_files is False

    def test_the_unit_reaches_the_facts_from_the_scale_declaration(self):
        """``resolved_facts`` is the ONLY way the axis becomes declared.

        This is the 08a finding made safe: the axis a check requires and the
        number four checks multiply by now come from one declaration, so they
        cannot describe different units.
        """
        cfg = TaskHealthConfig.model_validate(_tidmad_shaped_document())

        assert cfg.facts.value_scale_unit is None
        assert cfg.resolved_facts().value_scale_unit == "mV"
        # Everything else survives the fill unchanged.
        assert cfg.resolved_facts().encoding_family == "int8_symbol_stream"
        assert cfg.resolved_facts().file_group_size == 20

    def test_no_scale_means_the_axis_stays_absent(self):
        """Absence is a statement: a task with no physical scale declares none.

        Inventing an axis here would be the mirror of 08a's refused
        derivation — a declaration the task never made.
        """
        cfg = TaskHealthConfig()

        assert cfg.value_scale is None
        assert cfg.resolved_facts().value_scale_unit is None

    def test_a_task_may_declare_health_and_no_roster(self):
        """Legal absence, not an error — and distinguishable from an empty document."""
        cfg = TaskHealthConfig.model_validate({"facts": {"encoding_family": "continuous_float"}})

        assert cfg.roster == ()
        assert cfg.facts.encoding_family == "continuous_float"


class TestPhaseAIsNotPhaseB:
    """The positive-negative pair that IS the frozen contract (§3.1).

    A document naming code that does not exist yet must PARSE; the same
    document must fail at Phase B. If parsing ever started rejecting unknown
    ids, every out-of-tree task would be unable to author a config for its
    own plugins — the extension architecture would be closed by its schema.
    """

    def test_a_roster_naming_an_unregistered_check_parses(self):
        from execute_tools.health_checks import registry

        cfg = TaskHealthConfig.model_validate(
            {
                "roster": [
                    {
                        "gate_id": "some_external_gate",
                        "check": "definitely_not_registered_anywhere",
                        "disposition": "blocking",
                    }
                ]
            }
        )

        assert cfg.roster[0].check == "definitely_not_registered_anywhere"
        # And the id genuinely is unknown — otherwise this test proves nothing.
        assert "definitely_not_registered_anywhere" not in registry.all_registered()

    def test_an_unregistered_provider_id_parses(self):
        cfg = TaskHealthConfig.model_validate(
            {"providers": [{"provider_id": "vendor.some_future_provider"}]}
        )

        assert cfg.providers[0].provider_id == "vendor.some_future_provider"

    def test_an_opaque_provider_config_is_never_interpreted(self):
        """The framework passes provider config through without inspecting it."""
        payload = {"anything": {"nested": [1, 2, 3]}, "unknown_to_the_framework": True}

        binding = HealthProviderBinding(provider_id="p", config=payload)

        assert binding.config == payload


class TestPhaseARejectsIncoherentDocuments:
    """Each rejection names the offender, so the author can fix it.

    ``invalid disposition name`` appears here as one row rather than as its
    own test: it is enforced by the ``HealthDisposition`` declaration, and
    CLAUDE.md forbids building a test around what a declaration already
    guarantees. It is included only because the frozen design's acceptance
    criterion enumerates the class.
    """

    @pytest.mark.parametrize(
        "payload, expected_fragment",
        [
            pytest.param(
                {"roster": [{"gate_id": "  ", "check": "c", "disposition": "blocking"}]},
                "non-empty identifier",
                id="empty-gate-id",
            ),
            pytest.param(
                {"roster": [{"gate_id": "g", "check": "", "disposition": "blocking"}]},
                "non-empty identifier",
                id="empty-check-id",
            ),
            pytest.param(
                {"providers": [{"provider_id": " "}]},
                "non-empty identifier",
                id="empty-provider-id",
            ),
            pytest.param(
                {"plugins": [{"kind": "file", "ref": "/etc/health.py"}]},
                "is absolute",
                id="absolute-plugin-ref",
            ),
            pytest.param(
                {"plugins": [{"kind": "file", "ref": "~/health.py"}]},
                "Home expansion is",
                id="home-anchored-plugin-ref",
            ),
            pytest.param(
                {"plugins": [{"kind": "file", "ref": "   "}]},
                "non-empty identifier",
                id="blank-plugin-ref",
            ),
            pytest.param(
                {
                    "roster": [
                        {"gate_id": "g", "check": "a", "disposition": "blocking"},
                        {"gate_id": "g", "check": "b", "disposition": "recording"},
                    ]
                },
                "duplicate gate ids",
                id="duplicate-roster-entry",
            ),
            pytest.param(
                {"providers": [{"provider_id": "p"}, {"provider_id": "p"}]},
                "duplicate provider ids",
                id="duplicate-provider",
            ),
            pytest.param(
                {
                    "plugins": [
                        {"kind": "file", "ref": "./p.py"},
                        {"kind": "directory", "ref": "./p.py"},
                    ]
                },
                "duplicate plugin refs",
                id="duplicate-plugin-ref",
            ),
            pytest.param(
                {"roster": [{"gate_id": "g", "check": "c", "disposition": "advisory"}]},
                "blocking",
                id="invalid-disposition-name",
            ),
            pytest.param(
                {"unknown_top_level_key": 1},
                "Extra inputs are not permitted",
                id="unknown-field",
            ),
            pytest.param(
                {"roster": [{"gate_id": "g", "check": "c", "disposition": "blocking", "gate": 1}]},
                "Extra inputs are not permitted",
                id="unknown-roster-field",
            ),
            pytest.param(
                {"facts": {"value_scale_unit": "mV"}},
                "declared in two places",
                id="contradictory-facts-unit-declared-twice",
            ),
            pytest.param(
                {"facts": {"symbol_cardinality": 256}},
                "symbol_cardinality",
                id="contradictory-facts-cardinality-without-family",
            ),
            pytest.param(
                {"health_peek_files": [3, 10, 3]},
                "duplicate indices",
                id="duplicate-peek-file",
            ),
            pytest.param(
                {"health_peek_files": [-1]},
                "negative indices",
                id="negative-peek-file",
            ),
            pytest.param(
                {
                    "roster": [
                        {
                            "gate_id": "g",
                            "check": "c",
                            "disposition": "blocking",
                            "uses_health_peek_files": True,
                        }
                    ]
                },
                "declares no health_peek_files",
                id="peek-opt-in-without-a-declared-set",
            ),
            pytest.param(
                {"value_scale": {"unit": "mV", "units_per_sample": 0.0}},
                "greater than 0",
                id="non-positive-value-scale",
            ),
            pytest.param(
                {"value_scale": {"unit": "  ", "units_per_sample": 1.0}},
                "non-empty identifier",
                id="unnamed-value-scale-unit",
            ),
        ],
    )
    def test_rejected_at_construction(self, payload, expected_fragment):
        with pytest.raises(ValidationError) as excinfo:
            TaskHealthConfig.model_validate(payload)

        assert expected_fragment in str(excinfo.value), str(excinfo.value)


class TestTheTaskCannotStateFrameworkPolicy:
    """§3.7 made structural: there is no second copy to contradict.

    A document that ACCEPTED these keys and ignored them would be worse than
    one that rejects them — it would teach the author that they work.
    """

    @pytest.mark.parametrize("key", sorted(FRAMEWORK_OWNED_PARAMETER_KEYS))
    def test_every_framework_owned_key_is_refused_in_parameters(self, key):
        with pytest.raises(ValidationError) as excinfo:
            HealthRosterEntry(
                gate_id="g",
                check="c",
                disposition=HealthDisposition.BLOCKING,
                parameters={key: "whatever"},
            )

        assert "framework policy, not task parameters" in str(excinfo.value)

    def test_the_refused_set_is_exactly_the_operational_fields(self):
        """Pins the CONCEPT, not the field list.

        Every key here is either a ``GateConfig`` field the framework derives
        from the disposition, or a per-check policy key 08a already excluded
        from task thresholds. If someone adds a task-owned parameter to this
        set, task ownership silently shrinks; if someone removes an
        operational one, two copies of it come back.
        """
        assert FRAMEWORK_OWNED_PARAMETER_KEYS == {
            "gate_role",
            "on_pass",
            "on_fail",
            "short_circuit",
            "severity",
            "after_round",
            "aggregation",
            "peek_file_indices",
        }

    def test_task_thresholds_and_task_parameters_are_accepted(self):
        """The counterpart: what the task DOES own passes through untouched.

        Uses the exact keys 08a's corrected ``threshold_parameter_names``
        classify as task-owned, plus ``peek_samples`` — a parameter checks
        read, which 08a proved is NOT a threshold.
        """
        entry = HealthRosterEntry(
            gate_id="output_std_blocking",
            check="output_std",
            disposition=HealthDisposition.BLOCKING,
            parameters={"min_std_mv": 1.0, "peek_samples": 100000},
        )

        assert entry.parameters == {"min_std_mv": 1.0, "peek_samples": 100000}


class TestFactsVocabularyIsReusedNotRestated:
    """08a's ``TaskHealthFacts`` is the one facts vocabulary (§4.1)."""

    def test_the_document_embeds_08a_facts(self):
        cfg = TaskHealthConfig.model_validate({"facts": {"encoding_family": "int8_symbol_stream"}})

        assert isinstance(cfg.facts, TaskHealthFacts)
        assert isinstance(cfg.resolved_facts(), TaskHealthFacts)

    def test_an_axis_outside_08a_vocabulary_is_refused(self):
        """A second facts vocabulary cannot be smuggled in through this document."""
        with pytest.raises(ValidationError):
            TaskHealthConfig.model_validate({"facts": {"invented_axis": "x"}})


class TestValueScaleOwnsUnitAndNumberTogether:
    """§3.9 — separating them is what broke parity in 08a."""

    def test_both_halves_are_required(self):
        with pytest.raises(ValidationError):
            ValueScale(unit="mV")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            ValueScale(units_per_sample=0.3125)  # type: ignore[call-arg]

    def test_the_tidmad_factor_is_expressible_exactly(self):
        """40/128 is binary-exact, so the migration cannot lose precision."""
        assert ValueScale(unit="mV", units_per_sample=40.0 / 128.0).units_per_sample == 0.3125


class TestTaskHealthConfigIsConsumedOnlyThroughTheBindingSeam:
    """C1 landed the schema INERT; C2 wired it, so the guard is INVERTED.

    The design expected the inversion at C3, but C2's plugin loader is the
    first production module that legitimately reads ``config.plugins`` — so
    the guard fired one commit earlier than anticipated, exactly as 08a's
    equivalent did. Deleting it would discard a live invariant, so it now
    asserts the thing actually worth protecting: **the task health config is
    consumed only through the binding/composition seam.**

    A check, a runner or a script reading the task config directly would be a
    second consumer of task-owned truth, deciding for itself what a roster or
    a threshold means. That divergence is invisible to every behavioural test
    until the two readings disagree — which is precisely the duplicate-truth
    failure §3.7 exists to eliminate.

    The allowlist grows DELIBERATELY, one entry per commit that earns it, and
    a new consumer must be added here consciously rather than discovered
    later.

    Four independent defences against passing vacuously, all four of which
    08a needed after this exact guard silently searched the wrong directory:
    the root is asserted, the search's exit code is asserted, a positive
    probe must find the definition, and ``--untracked`` is passed so a
    brand-new production module cannot hide.
    """

    DEFINING_MODULE = "execute_tools/health_checks/_task_health_config.py"

    ALLOWED_CONSUMERS = (
        # C2 — resolves and loads the plugin refs the document declares.
        "execute_tools/health_checks/_plugin_binding.py",
        # C4 — composes the roster with framework policy.
        "execute_tools/health_checks/_composition.py",
        # C4 — the one materialization entry point, which parses the bound
        # document and hands it to composition.
        "execute_tools/health_checks/config.py",
    )

    @staticmethod
    def _git_grep(pattern: str) -> list[str]:
        proc = subprocess.run(
            ["git", "grep", "-nE", "--untracked", pattern, "--", *PRODUCTION_PACKAGES],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        # 0 = matches, 1 = no matches. Anything else means the search did not
        # run, which must not be read as "no importers".
        assert proc.returncode in (0, 1), (
            f"git grep failed (rc={proc.returncode}) in {REPO_ROOT}: {proc.stderr.strip()}"
        )
        # Documentation is PROSE, not a consumer — a module README naming the
        # config type describes the seam; it cannot import or read it. Added
        # when the S4 onboarding stream shipped READMEs inside the swept
        # packages (the same principle the standard-views census applies to
        # .py docstrings).
        return [
            line for line in proc.stdout.splitlines() if not line.split(":", 1)[0].endswith(".md")
        ]

    def test_repo_root_resolves_to_this_checkout(self):
        """Guards the guard: a wrong root would make the grep below vacuous."""
        assert (REPO_ROOT / ".git").exists()
        assert (REPO_ROOT / "execute_tools" / "health_checks" / "_task_health_config.py").is_file()

    def test_the_grep_probe_actually_finds_things(self):
        """Proves the search works, so its emptiness below is real evidence."""
        hits = self._git_grep(r"TaskHealthConfig")
        assert any("_task_health_config.py" in line for line in hits), hits

    def test_every_production_consumer_is_on_the_seam_allowlist(self):
        offenders = [
            line
            for line in self._git_grep(r"_task_health_config|TaskHealthConfig")
            if self.DEFINING_MODULE not in line and not line.startswith(self.ALLOWED_CONSUMERS)
        ]

        assert not offenders, (
            "the task health config is task-owned truth and must be consumed "
            "only through the binding/composition seam; a second reader would "
            "decide for itself what a roster or threshold means:\n" + "\n".join(offenders)
        )

    def test_the_allowlist_is_not_vacuous(self):
        """An allowlist naming a module that does not consume it proves nothing.

        Without this, deleting the real consumer would leave the guard green
        and the allowlist describing a relationship that no longer exists.
        """
        consumers = {
            line.split(":", 1)[0]
            for line in self._git_grep(r"_task_health_config|TaskHealthConfig")
            if self.DEFINING_MODULE not in line
        }

        assert set(self.ALLOWED_CONSUMERS) == consumers, (
            f"allowlist {sorted(self.ALLOWED_CONSUMERS)} does not match the "
            f"actual consumers {sorted(consumers)}"
        )
