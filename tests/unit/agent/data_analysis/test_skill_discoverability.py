from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.reference_packs import builtin_pack_refs
from tests.helpers.data_analysis_discoverability import PARAPHRASES, discoverability_audit


def test_every_reference_skill_is_visible_under_method_name_free_paraphrases() -> None:
    """Catches a useful skill becoming unreachable before the LLM can select it."""

    snapshot = discover_skills(builtin_pack_refs("core-analysis", "time-series"))
    assert set(PARAPHRASES) == {item.card.skill_id for item in snapshot.skills}

    misses = [row for row in discoverability_audit(limit=8) if not row["recalled"]]
    assert misses == []
