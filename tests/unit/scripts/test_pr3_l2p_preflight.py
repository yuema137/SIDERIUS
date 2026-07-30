"""Pytest wrapper for the P3-L2p zero-LLM launch preflight (protocol §3.3).

Asserts every launch invariant across all six scenario x arm cells with
mocked LLMs — pipeline mode, placeholder resolution, exact treatment
isolation, fixture-hash stability. ZERO real LLM calls.
"""

from scripts.pr3_l2_calibration.preflight import main as preflight_main


def test_preflight_all_invariants():
    results = preflight_main()  # raises AssertionError on any violation
    # Treatment isolation summarized: block present iff T.
    for scenario in ("S1", "S2"):
        assert results[f"{scenario}_T"]["proposer_block_present"] is True
        assert results[f"{scenario}_C"]["proposer_block_present"] is False
        assert results[f"{scenario}_D"]["proposer_block_present"] is False
        assert results[f"{scenario}_treatment_token_increase"] > 0
    assert results["fixture_hashes"]["S1"] != results["fixture_hashes"]["S2"]
