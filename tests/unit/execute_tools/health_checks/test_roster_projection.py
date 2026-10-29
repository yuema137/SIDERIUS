"""Public Health roster projection used by the console Task panel."""

from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.roster_projection import project_health_roster


def test_roster_reports_declared_role_per_gate(tmp_path):
    """Defect: the projection collapses recording gates into blocking (or reads the
    role from an action/name), so the Task panel misstates which gates invalidate."""
    config = tmp_path / "task_health.yaml"
    config.write_text(
        "facts:\n  encoding_family: continuous_float\n"
        "roster:\n"
        "  - {gate_id: g_block, check: output_std, disposition: blocking}\n"
        "  - {gate_id: g_record, check: per_file_output_std, disposition: recording}\n"
    )
    roster = project_health_roster(str(config))
    assert roster.declaration == "declared"
    assert {gate.gate_id: (gate.checks, gate.role) for gate in roster.gates} == {
        "g_block": (("output_std",), "blocking"),
        "g_record": (("per_file_output_std",), "observational"),
    }


def test_explicit_none_is_a_named_absence():
    """Defect: a declared absence displayed like an omitted declaration."""
    roster = project_health_roster(HealthBindingState.EXPLICIT_NONE)
    assert (roster.declaration, roster.gates) == ("explicit_none", ())
