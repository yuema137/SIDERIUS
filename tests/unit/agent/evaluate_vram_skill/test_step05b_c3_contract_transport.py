"""Step 05b C3 — the contract crosses the isolated pre-flight boundary.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
C3, §20 (an IPC-spec field is transport, not configuration).

The production pre-flight runs in a CHILD PROCESS, so what C2 added to the
in-process probe is unreachable from production until the contract can cross
that boundary. C3 carries it BY VALUE on the transient ``IsolatedProbeSpec``
— the same omit-vs-broken rule the ``--model_io_json`` transport already
uses for the training and inference children.

IPC has one failure mode that shape tests cannot see: **a field that
serializes but never arrives**. A grep for the field name would pass while
the worker quietly forwarded ``None`` and the child probed the legacy shape —
reporting a capacity number for a different tensor than the parent asked
about. So the assertions below are about ARRIVAL, at the ``run_skill``
boundary, and about the two ways arrival can fail:

1. the value is dropped or mangled between parent and child;
2. a PRESENT-but-unrebuildable field degrades to ``None`` instead of
   failing.

Backward compatibility is the third: a spec written before this field
existed must still load and still behave exactly as it did.

Two cases are deliberately ABSENT. A malformed contract on the PARENT side is
rejected by the spec's own typed field, so a test would only re-assert what
the declaration enforces; and ``HardwareSnapshot``'s read surface is already
pinned by ``test_hardware_snapshot_satisfies_run_skill_surface``, which fails
if C3 had widened it.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.schemas.custom_loss_contract import (
    EqualShapeApplicability,
    build_custom_loss_contract_snapshot,
)
from agent.schemas.model_io_contract import (
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.skills.evaluate_vram_skill import preflight_worker_main
from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeSpec
from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets
from tests.helpers.step04a_fixtures import tidmad_model_io


def _loss_snapshot(extent: int = 2):
    tensor = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(fixed=extent)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    return build_custom_loss_contract_snapshot(
        tensor,
        tensor,
        EqualShapeApplicability(dtype=tensor.dtype, rank=2),
    )


def _spec(tmp_path: Path, **overrides) -> IsolatedProbeSpec:
    base = {
        "label": "s05b_c3",
        "model_type": "punet",
        "result_path": str(tmp_path / "s05b_c3.json"),
        "worker_memory_limit_bytes": 8 * 1024**3,
    }
    base.update(overrides)
    return IsolatedProbeSpec(**base)


# ---------------------------------------------------------------------------
# 1. Arrival
# ---------------------------------------------------------------------------


class TestTheContractArrivesInTheChild:
    def test_the_parent_puts_it_on_the_spec(self, tmp_path, monkeypatch):
        """The PARENT hop. Found by a surviving mutation: dropping the
        contract in ``run_production_preflight``'s spec construction left
        every other transport assertion green, because they all start from a
        spec that already carries it. The caller's argument has to be shown
        reaching the document that crosses the boundary."""
        from agent.skills.evaluate_vram_skill import preflight_adapter
        from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeResult

        contract = tidmad_model_io(num_classes=16)
        loss_snapshot = _loss_snapshot()
        captured: dict[str, IsolatedProbeSpec] = {}

        def _capture(spec, **_kwargs):
            captured["spec"] = spec
            return IsolatedProbeResult(label=spec.label, outcome="COMPLETED_MEASUREMENT")

        monkeypatch.setattr(preflight_adapter, "run_isolated_preflight", _capture)
        monkeypatch.setattr(preflight_adapter, "build_hardware_snapshot", lambda _ctx: None)

        preflight_adapter.run_production_preflight(
            model_type="punet",
            model_config={},
            train_config={},
            loss_config={},
            vram_budget_gb=None,
            hardware_context=None,
            workspace=tmp_path,
            label="s05b_c3_parent",
            model_io_contract=contract,
            expected_custom_loss_snapshot=loss_snapshot,
            # Step 11 C1 — keyword-only with no default, so this transport
            # test must state the run-scoped dirs like production does.
            plugin_dir="/run/scoped/plugins",
            loss_dir="/run/scoped/losses",
        )

        assert captured["spec"].model_io_contract == contract
        assert captured["spec"].expected_custom_loss_snapshot == loss_snapshot
        assert captured["spec"].plugin_dir == "/run/scoped/plugins"
        assert captured["spec"].loss_dir == "/run/scoped/losses"

    def test_custom_loss_snapshot_reaches_the_worker_consumption_boundary(
        self, tmp_path, monkeypatch
    ):
        snapshot = _loss_snapshot()
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(
            _spec(tmp_path, expected_custom_loss_snapshot=snapshot).model_dump_json(),
            encoding="utf-8",
        )
        seen = {}

        def _fake_run_skill(_sandbox, **kwargs):
            seen.update(kwargs)
            return {"status": "success", "feasible": True}

        monkeypatch.setattr("agent.skills.evaluate_vram_skill.wrapper.run_skill", _fake_run_skill)
        preflight_worker_main.main([str(spec_path)])

        assert seen["expected_custom_loss_snapshot"] == snapshot

    def test_it_round_trips_through_the_spec_json_unchanged(self, tmp_path):
        """Serialized, re-read the way the worker reads it, and revalidated
        to an EQUAL contract — not merely to something truthy."""
        contract = tidmad_model_io(num_classes=16)
        spec = _spec(tmp_path, model_io_contract=contract)

        reloaded = json.loads(spec.model_dump_json())
        assert ModelIOContract(**reloaded["model_io_contract"]) == contract

    def test_the_worker_forwards_it_to_run_skill(self, tmp_path, monkeypatch):
        """THE transport assertion: asserted where the value is CONSUMED, not
        by reading the spec file back. Deleting the forwarding argument in
        ``preflight_worker_main`` makes this RED; a grep for the field name
        would not."""
        contract = tidmad_model_io(num_classes=16)
        spec_path = tmp_path / "spec.json"
        budgets = ProbeBudgets(single_probe_seconds=321.0, preflight_total_seconds=987.0)
        spec_path.write_text(
            _spec(
                tmp_path,
                model_io_contract=contract,
                probe_budgets=budgets,
            ).model_dump_json(),
            encoding="utf-8",
        )

        seen: dict[str, object] = {}

        def _fake_run_skill(_sandbox, **kwargs):
            seen.update(kwargs)
            return {"status": "success", "feasible": True, "estimated_gb": 0.0, "limit_gb": 0.0}

        monkeypatch.setattr("agent.skills.evaluate_vram_skill.wrapper.run_skill", _fake_run_skill)
        preflight_worker_main.main([str(spec_path)])

        assert seen["model_io_contract"] == contract
        assert seen["probe_budgets"] == budgets

    def test_an_absent_field_forwards_none(self, tmp_path, monkeypatch):
        """Absence is the legacy no-contract path, all the way down — the
        child must not invent one, and must not refuse."""
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(_spec(tmp_path).model_dump_json(), encoding="utf-8")

        seen: dict[str, object] = {}
        monkeypatch.setattr(
            "agent.skills.evaluate_vram_skill.wrapper.run_skill",
            lambda _s, **kw: (seen.update(kw), {"status": "success", "feasible": True})[1],
        )
        preflight_worker_main.main([str(spec_path)])

        assert seen["model_io_contract"] is None


# ---------------------------------------------------------------------------
# 2. A broken field fails loudly
# ---------------------------------------------------------------------------


class TestAMalformedContractNeverBecomesNone:
    def test_malformed_custom_loss_snapshot_stops_before_run_skill(self, tmp_path, monkeypatch):
        result_path = tmp_path / "s05b_c3.json"
        spec_path = tmp_path / "spec.json"
        payload = json.loads(
            _spec(tmp_path, expected_custom_loss_snapshot=_loss_snapshot()).model_dump_json()
        )
        payload["expected_custom_loss_snapshot"]["sha256"] = "0" * 64
        spec_path.write_text(json.dumps(payload), encoding="utf-8")

        def _must_not_run(_sandbox, **_kwargs):
            raise AssertionError("run_skill was reached with a broken loss snapshot")

        monkeypatch.setattr("agent.skills.evaluate_vram_skill.wrapper.run_skill", _must_not_run)
        preflight_worker_main.main([str(spec_path)])

        written = json.loads(result_path.read_text(encoding="utf-8"))
        assert written["outcome"] == "PROBE_INFRASTRUCTURE_FAILURE"
        assert "expected_custom_loss_snapshot" in written["detail"]

    def test_the_worker_reports_it_as_an_infrastructure_failure(self, tmp_path, monkeypatch):
        """Present-but-unrebuildable is a TRANSPORT failure, and degrading it
        to ``None`` would silently probe the legacy shape. The result names
        the field so an operator can tell this from a capacity verdict."""
        result_path = tmp_path / "s05b_c3.json"
        spec_path = tmp_path / "spec.json"
        payload = json.loads(_spec(tmp_path, model_io_contract=tidmad_model_io()).model_dump_json())
        payload["model_io_contract"] = {"input": "not a tensor contract"}
        spec_path.write_text(json.dumps(payload), encoding="utf-8")

        def _must_not_run(_sandbox, **_kwargs):
            raise AssertionError("run_skill was reached with a broken contract")

        monkeypatch.setattr("agent.skills.evaluate_vram_skill.wrapper.run_skill", _must_not_run)
        preflight_worker_main.main([str(spec_path)])

        written = json.loads(result_path.read_text(encoding="utf-8"))
        assert written["outcome"] == "PROBE_INFRASTRUCTURE_FAILURE"
        assert "model_io_contract" in written["detail"]


# ---------------------------------------------------------------------------
# 3. Backward compatibility
# ---------------------------------------------------------------------------


class TestOldSpecsStillLoad:
    def test_a_spec_json_written_before_the_field_existed_validates(self, tmp_path):
        """Replay compatibility: the transient spec has no manifest and no
        migration, so an old document must simply keep working."""
        legacy = json.loads(_spec(tmp_path).model_dump_json())
        legacy.pop("model_io_contract")

        assert IsolatedProbeSpec(**legacy).model_io_contract is None
