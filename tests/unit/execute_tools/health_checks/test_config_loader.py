"""YAML config loader semantics.

Covers the rev-6 HealthGate config classes and their loader plus the
legacy rev-3 classes still kept until commit-6. See
``docs/design/pluggable_health_checks.md`` §3 for the schema and §15.2
for the per-commit test scope rule of thumb.

Config parsing only — this file does NOT exercise any check's ``run`` method.
"""

from __future__ import annotations

import os
import shutil
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from execute_tools.health_checks import config as config_module
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.config import (
    _DEFAULT_CONFIG_PATH,
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
    clear_health_gates_config_cache,
    load_composed_health_config,
    load_health_gates_config,
    materialize_effective_config,
)
from execute_tools.health_checks.schemas import GateAction


@pytest.fixture(autouse=True)
def _clear_caches():
    """Process-wide gate-config cache is cleared before and after every
    test in this file."""
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


# ---------------------------------------------------------------------------
# rev-6 schemas — CheckRef
# ---------------------------------------------------------------------------


class TestCheckRef:
    @pytest.mark.parametrize("peek", ["task_health_peek", "arbitrary_typo", ""])
    def test_all_strings_refuse_before_profile_access(self, monkeypatch, peek):
        """Retired marker cannot be rescued by a profile, even when unavailable."""

        def no_profile():
            raise AssertionError("profile accessed before string refusal")

        monkeypatch.setattr(config_module, "resolve_dataset_profile", no_profile)
        with pytest.raises(ValidationError, match="explicit list of file indices"):
            CheckRef(name="synthetic", config={"peek_file_indices": peek})

    @pytest.mark.parametrize("peek", [[2, 7], None, 2, (2, 7)])
    def test_non_string_plugin_values_are_not_reinterpreted(self, peek):
        """Marker retirement must not introduce a new plugin-config schema."""
        result = CheckRef(name="synthetic", config={"peek_file_indices": peek})
        assert result.config["peek_file_indices"] == peek

    def test_defaults(self):
        r = CheckRef(name="output_diversity")
        assert r.config == {}

    def test_config_dict_propagates(self):
        r = CheckRef(
            name="output_diversity",
            config={"min_unique_int8_values": 5, "peek_samples": 100_000},
        )
        assert r.config["min_unique_int8_values"] == 5
        assert r.config["peek_samples"] == 100_000

    def test_task_owned_peek_list_survives_composition_and_materialization(self, tmp_path):
        """The supported replacement is an actual task declaration, not a marker."""
        task = tmp_path / "task_health.yaml"
        task.write_text(
            "health_peek_files: [2, 7]\n"
            "roster:\n"
            "  - gate_id: synthetic_guard\n"
            "    check: output_diversity\n"
            "    disposition: blocking\n"
            "    uses_health_peek_files: true\n"
        )
        path, _ = materialize_effective_config(
            None, None, str(tmp_path / "workspace"), task_health_binding=str(task)
        )
        config = load_health_gates_config(path)
        assert config.health_gates[0].checks[0].config["peek_file_indices"] == [2, 7]


# ---------------------------------------------------------------------------
# rev-6 schemas — ActionConfig
# ---------------------------------------------------------------------------


class TestActionConfig:
    def test_valid_action(self):
        ac = ActionConfig(action=GateAction.CONTINUE)
        assert ac.action is GateAction.CONTINUE

    def test_action_accepts_string_value(self):
        """The YAML loader receives raw strings — Pydantic coerces to
        the GateAction StrEnum via its ``__init__``."""
        ac = ActionConfig.model_validate({"action": "invalidate_round"})
        assert ac.action is GateAction.INVALIDATE_ROUND

    def test_unknown_action_string_raises(self):
        with pytest.raises(ValidationError):
            ActionConfig.model_validate({"action": "not_a_real_action"})

    @pytest.mark.parametrize("retired", ["skip_iter", "skip_to_formal"])
    def test_retired_action_refuses_at_the_config_gate(self, retired: str):
        """F-SCANC-1 — the config-surface witness: a YAML-shaped mapping
        declaring a retired action REFUSES with a ValidationError naming
        the permitted values, instead of composing a gate whose action the
        runtime cannot act on (the pre-retirement state: declared-but-
        unreachable semantics). Fails when: the vocabulary regains the
        member or an alias maps it through."""
        with pytest.raises(ValidationError, match=r"continue|invalidate_round"):
            ActionConfig.model_validate({"action": retired})


# ---------------------------------------------------------------------------
# rev-6 schemas — GateConfig
# ---------------------------------------------------------------------------


def _minimal_gate_kwargs(**overrides):
    """Build a minimal-valid GateConfig kwargs dict; overrides win."""
    base = {
        "id": "test_gate",
        "after_round": 1,
        "checks": [CheckRef(name="output_diversity")],
        "on_pass": ActionConfig(action=GateAction.CONTINUE),
        "on_fail": ActionConfig(action=GateAction.INVALIDATE_ROUND),
    }
    base.update(overrides)
    return base


class TestGateConfig:
    def test_minimal_valid(self):
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.id == "test_gate"
        assert g.after_round == 1
        assert g.short_circuit is True  # D4: default True
        assert g.reason == ""

    def test_short_circuit_default_is_true(self):
        """D4: per-gate ``short_circuit`` moves to gate level, default True."""
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.short_circuit is True

    def test_short_circuit_can_be_disabled(self):
        g = GateConfig(**_minimal_gate_kwargs(short_circuit=False))
        assert g.short_circuit is False

    def test_empty_checks_list_rejected(self):
        """D2: min_length=1 — a gate with no checks is a config error."""
        with pytest.raises(ValidationError):
            GateConfig(**_minimal_gate_kwargs(checks=[]))

    def test_on_pass_required(self):
        """D1: on_pass is required, no default."""
        kwargs = _minimal_gate_kwargs()
        del kwargs["on_pass"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_on_fail_required(self):
        """D1: on_fail is required, no default."""
        kwargs = _minimal_gate_kwargs()
        del kwargs["on_fail"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_reason_default_empty(self):
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.reason == ""

    def test_missing_id_raises(self):
        kwargs = _minimal_gate_kwargs()
        del kwargs["id"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_missing_after_round_raises(self):
        kwargs = _minimal_gate_kwargs()
        del kwargs["after_round"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# rev-6 schemas — HealthChecksConfig
# ---------------------------------------------------------------------------


class TestHealthChecksConfig:
    def test_empty_health_gates_list_is_valid(self):
        """Empty list = no gates fire, but the config itself is valid.
        Operators may temporarily disable all gates by clearing the list."""
        cfg = HealthChecksConfig(health_gates=[])
        assert cfg.health_gates == []

    def test_single_gate_is_valid(self):
        g = GateConfig(**_minimal_gate_kwargs())
        cfg = HealthChecksConfig(health_gates=[g])
        assert len(cfg.health_gates) == 1
        assert cfg.health_gates[0].id == "test_gate"

    def test_duplicate_ids_rejected(self):
        """D3: unique gate ids required, else ValueError with dupe list."""
        g1 = GateConfig(**_minimal_gate_kwargs(id="duplicate_id"))
        g2 = GateConfig(**_minimal_gate_kwargs(id="duplicate_id"))
        with pytest.raises(ValidationError) as exc_info:
            HealthChecksConfig(health_gates=[g1, g2])
        # The Pydantic ValidationError wraps the ValueError; the dupe list
        # must appear in the message.
        assert "duplicate_id" in str(exc_info.value).lower()

    def test_duplicate_ids_message_lists_all_dupes(self):
        """The ValueError message lists every duplicated id, not just one."""
        gates = [
            GateConfig(**_minimal_gate_kwargs(id="dup_a")),
            GateConfig(**_minimal_gate_kwargs(id="dup_a")),
            GateConfig(**_minimal_gate_kwargs(id="dup_b")),
            GateConfig(**_minimal_gate_kwargs(id="dup_b")),
        ]
        with pytest.raises(ValidationError) as exc_info:
            HealthChecksConfig(health_gates=gates)
        msg = str(exc_info.value).lower()
        assert "dup_a" in msg
        assert "dup_b" in msg


# ---------------------------------------------------------------------------
# load_health_gates_config
# ---------------------------------------------------------------------------


class TestLoadHealthGatesConfig:
    def test_missing_explicit_path_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "missing_health_checks.yaml"
        with pytest.raises(FileNotFoundError):
            load_health_gates_config(path=str(missing))

    def test_loads_valid_yaml(self, tmp_path):
        p = tmp_path / "hc.yaml"
        p.write_text(
            textwrap.dedent(
                """
                health_gates:
                  - id: "g1"
                    after_round: 1
                    checks:
                      - name: output_diversity
                        config:
                          min_unique_int8_values: 5
                    on_pass:
                      action: continue
                    on_fail:
                      action: invalidate_round
                """
            ).lstrip()
        )
        cfg = load_health_gates_config(path=str(p))
        assert len(cfg.health_gates) == 1
        g = cfg.health_gates[0]
        assert g.id == "g1"
        assert g.after_round == 1
        assert g.checks[0].config["min_unique_int8_values"] == 5
        assert g.on_pass.action is GateAction.CONTINUE
        assert g.on_fail.action is GateAction.INVALIDATE_ROUND

    def test_a_rosterless_file_stays_empty_without_a_task_binding(self, tmp_path):
        """Step 08b C5 — the A/B distinction, at the loader.

        A file carrying no roster is not a statement that there are no gates:
        after C5 the framework file carries POLICY only, so "no gates here"
        is the normal case and the roster comes from the task (state A).
        Declaring that a run has no Health binding at all is a DIFFERENT
        claim, made explicitly — and the two must not collapse, or a task
        that deliberately declares no health would silently inherit
        another's family.
        """
        p = tmp_path / "empty.yaml"
        p.write_text("")

        composed = load_health_gates_config(path=str(p))
        explicit_none, _, _ = load_composed_health_config(str(p), HealthBindingState.EXPLICIT_NONE)

        assert composed.health_gates == []
        assert explicit_none.health_gates == []

    def test_path_override_bypasses_cache(self, tmp_path):
        """Passing ``path=`` should always re-read from disk."""
        p = tmp_path / "hc.yaml"
        # A file with its OWN roster, so the reload is compared against a
        # roster rather than against the composed task default.
        p.write_text(
            textwrap.dedent(
                """
                health_gates:
                  - id: "g0"
                    after_round: 1
                    checks:
                      - name: output_diversity
                    on_pass: {action: continue}
                    on_fail: {action: invalidate_round}
                """
            ).lstrip()
        )
        cfg1 = load_health_gates_config(path=str(p))
        p.write_text(
            textwrap.dedent(
                """
                health_gates:
                  - id: "g1"
                    after_round: 1
                    checks:
                      - name: output_diversity
                    on_pass: {action: continue}
                    on_fail: {action: invalidate_round}
                """
            ).lstrip()
        )
        cfg2 = load_health_gates_config(path=str(p))
        assert [g.id for g in cfg1.health_gates] == ["g0"]
        assert [g.id for g in cfg2.health_gates] == ["g1"]

    def test_default_path_loads_framework_policy_without_task_gates(self):
        """The framework default must not silently select task science."""
        cfg = load_health_gates_config()
        assert cfg.health_gates == []

    def test_shipped_config_all_actions_valid(self):
        """Every on_pass/on_fail action string in the shipped YAML must
        resolve to a real GateAction enum member."""
        cfg = load_health_gates_config()
        for g in cfg.health_gates:
            # Type check: if the string was invalid, ValidationError would
            # have raised during load.
            assert isinstance(g.on_pass.action, GateAction)
            assert isinstance(g.on_fail.action, GateAction)


class TestTheShippedDefaultsDoNotDependOnTheWorkingDirectory:
    """F-7 — the shipped-config defaults are anchored to THIS checkout.

    Framework paths must resolve from this checkout rather than the caller's
    working directory.

    CLAUDE.md's portability rule is the governing one: path resolution derives
    from the file's own location or a supplied root, never from the caller's
    cwd.
    """

    def test_the_loaders_resolve_from_an_unrelated_working_directory(self, tmp_path, monkeypatch):
        """Fails as: FileNotFoundError on a relative shipped-config path.

        All three routes are exercised because they fail separately: the
        zero-argument loader resolves the FRAMEWORK default, and the other two
        resolve an absolute framework path and then compose the TASK default,
        which is a second constant.
        """
        from execute_tools.health_checks.candidate_eligibility import resolve_scientific_gate_ids

        monkeypatch.chdir(tmp_path)

        assert load_health_gates_config(None).health_gates == []
        assert resolve_scientific_gate_ids() == frozenset()
        assert load_health_gates_config(_DEFAULT_CONFIG_PATH).health_gates == []

    def test_framework_default_points_into_this_package(self):
        repo_root = Path(__file__).resolve().parents[4]

        assert (
            Path(_DEFAULT_CONFIG_PATH)
            == repo_root / "src/execute_tools/health_checks/resources/health_checks.yaml"
        )


class TestAMaterializedConfigDoesNotRecordWhichCheckoutProducedIt:
    """F-7, second half — resolve absolutely, RECORD relatively.

    Anchoring the shipped-config defaults to ``SIDERIUS_ROOT`` was the right
    fix for LOADING and the wrong string to WRITE DOWN. The materialization
    header renders the source path, so the artifact began naming
    ``/home/<whoever>/<some-checkout>/configs/health_checks.yaml`` — the
    identity of the machine that produced it — and its byte length then varied
    by environment. Two runs of the SAME code observed 4945 and 5009 bytes for
    the same document, differing only in where the checkout lived.

    The Step-09.5a envelope oracle caught the length change, but the oracle is
    the weaker instrument twice over: it notices only because the number
    happened to move, and re-baselining it would have been impossible, because
    the number depends on the machine. A persisted artifact carrying one
    developer's absolute path is precisely the failure CLAUDE.md's portability
    section exists for, so closing F-7 must not reintroduce it one layer up.

    The property below is the one that means something: the same config
    materialized from two DIFFERENT checkout roots produces byte-identical
    output.
    """

    @staticmethod
    def _second_checkout(tmp_path: Path) -> Path:
        """A second checkout of the same framework config, at another path."""
        root = tmp_path / "another" / "checkout" / "at" / "a" / "much" / "longer" / "path"
        (root / "resources").mkdir(parents=True)
        shutil.copyfile(Path(_DEFAULT_CONFIG_PATH), root / "resources/health_checks.yaml")
        return root

    def test_the_artifact_is_byte_identical_across_two_checkout_roots(self, tmp_path, monkeypatch):
        """Fails as: two identical runs producing different bytes.

        The path lengths are deliberately very different, so a renderer that
        leaked the absolute path cannot pass by coincidence.
        """
        from_real = Path(
            materialize_effective_config(None, None, str(tmp_path / "ws_real"))[0]
        ).read_bytes()

        root_b = self._second_checkout(tmp_path)
        from execute_tools.health_checks import _policy_resources

        monkeypatch.setattr(config_module, "SIDERIUS_ROOT", None)
        monkeypatch.setattr(
            _policy_resources,
            "__file__",
            str(root_b / "_policy_resources.py"),
        )
        clear_health_gates_config_cache()
        from_other = Path(
            materialize_effective_config(None, None, str(tmp_path / "ws_other"))[0]
        ).read_bytes()

        assert from_real == from_other, (
            "the materialized effective config differs between two checkouts of "
            "the same framework config — it is recording which machine produced it"
        )
        assert b"# source: execute_tools/health_checks/resources/health_checks.yaml\n" in from_real

    def test_an_external_config_keeps_its_absolute_path(self, tmp_path):
        """The deliberate exception, pinned so it reads as a decision.

        For a config OUTSIDE the checkout the absolute path is the informative
        answer, and no repo-relative rendering of it could be honest or
        stable. Byte-stability is not available there and is not claimed.
        """
        external = tmp_path / "outside" / "custom_health.yaml"
        external.parent.mkdir(parents=True)
        shutil.copyfile(Path(_DEFAULT_CONFIG_PATH), external)

        written = Path(
            materialize_effective_config(str(external), None, str(tmp_path / "ws"))[0]
        ).read_text(encoding="utf-8")

        assert f"# source: {external}\n" in written

    def test_the_recorded_path_is_never_absolute_for_an_in_repo_config(self):
        """The rule itself, stated over both shipped configs.

        A census rather than one example: an in-repo config must never render
        absolutely, whichever one a run names.
        """
        root = Path(__file__).resolve().parents[4]
        for shipped in (
            Path(_DEFAULT_CONFIG_PATH),
            root / "configs/health/health_checks_baseline_observe_mode.yaml",
        ):
            rendered = config_module._record_path(str(shipped))
            assert not os.path.isabs(rendered), f"{shipped.name} rendered absolutely: {rendered}"
            assert rendered.startswith(("configs/", "execute_tools/")), rendered


@pytest.mark.parametrize(
    "content", [None, "health_policy: [", "health_policy: {blocking: {on_fail: wrong}}"]
)
def test_explicit_invalid_policy_never_reads_default(tmp_path, monkeypatch, content):
    """A fallback would hide an explicit missing/malformed/invalid operator input."""
    import yaml

    from execute_tools.health_checks import _composition

    def forbidden():
        pytest.fail("explicit policy failure attempted default rescue")

    monkeypatch.setattr(_composition, "read_default_policy", forbidden)
    path = tmp_path / "explicit.yaml"
    if content is not None:
        path.write_text(content)
    with pytest.raises((FileNotFoundError, yaml.YAMLError, ValidationError)):
        load_composed_health_config(str(path))


@pytest.mark.parametrize("selection", ["omitted", "empty_path", "blank", "empty"])
def test_empty_inputs_keep_the_same_resolved_default(tmp_path, selection):
    """Path omission and accepted empty documents converge only when policy is needed."""
    source = None
    if selection == "empty_path":
        source = ""
    elif selection in {"blank", "empty"}:
        path = tmp_path / "explicit.yaml"
        path.write_text("" if selection == "blank" else "{}\n")
        source = str(path)
    config, _, _ = load_composed_health_config(source)
    policy = config.resolved_policy()
    assert policy["blocking"].on_fail is GateAction.INVALIDATE_ROUND
    assert policy["blocking"].check_config == {"aggregation": "all_pass"}
    assert policy["recording"].on_fail is GateAction.CONTINUE


@pytest.mark.parametrize("damage", [None, "", "{}", "health_policy: {}", "health_policy: []"])
def test_damaged_default_refuses_but_complete_explicit_policy_is_independent(
    tmp_path, monkeypatch, damage
):
    """Default validation is lazy and required; an explicit policy never needs that asset."""
    from execute_tools.health_checks import _policy_resources

    explicit = tmp_path / "explicit.yaml"
    explicit.write_bytes(Path(_DEFAULT_CONFIG_PATH).read_bytes())
    package = tmp_path / "installed_health"
    resource = package / "resources/health_checks.yaml"
    resource.parent.mkdir(parents=True)
    if damage is not None:
        resource.write_text(damage)
    monkeypatch.setattr(_policy_resources, "__file__", str(package / "_policy_resources.py"))
    # Location is inert even if the default cannot be read.
    assert config_module.default_health_policy_path() == str(resource)
    with pytest.raises((FileNotFoundError, ValidationError)):
        load_health_gates_config()
    assert (
        load_health_gates_config(str(explicit)).resolved_policy()["blocking"].on_fail
        is GateAction.INVALIDATE_ROUND
    )


def test_no_python_default_policy_values_compete_with_the_resource():
    """Restoring an authored DispositionPolicy table creates a second default authority."""
    import ast

    package = Path(config_module.__file__).parent
    constructors = []
    for source in package.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DispositionPolicy"
            ):
                constructors.append(f"{source.name}:{node.lineno}")
    assert constructors == [], f"authored policy values outside the resource: {constructors}"


# Note (commit-6): TestLegacyClasses + TestLegacyLoader used to live here
# (4 tests exercising CheckConfig, HealthCheckConfig, load_health_check_config,
# clear_config_cache). The legacy config classes and their loader were
# removed in commit-6; see docs/design/pluggable_health_checks.md §14.
