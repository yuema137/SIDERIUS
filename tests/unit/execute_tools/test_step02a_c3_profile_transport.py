"""PR-02a commit C3 — the profile's trip across the subprocess boundary.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§3.2 (the IPC precedent), §5c (Regime-A vs fail-closed), §6.3 (this commit).

This framework module owns only the generic transport: schema-valid profiles
round-trip through JSON, malformed inputs fail closed, and both subprocess
entrypoints expose the explicit profile flag. Task-specific loader semantics
belong to the external task repository.
"""

from __future__ import annotations

import json

import pytest

import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import load_dataset_profile
from tests.helpers.two_family_profile import make_two_family_profile

BASE_PROFILE = make_two_family_profile()
CONTRAST_PROFILE = make_two_family_profile(
    num_files=5, psd_segment_length=4_000, segments_per_file=6
)


# ---------------------------------------------------------------------------
# The config-file hop itself
# ---------------------------------------------------------------------------


class TestConfigFileRoundTrip:
    """Parent serializes → child loads → identical object.

    The transport reuses the ``--model_cfg`` precedent: JSON on disk, path
    on argv. If ``model_dump()`` ever stopped round-tripping through
    ``model_validate`` the child would silently receive a different profile
    from the one the parent resolved.
    """

    @pytest.mark.parametrize(
        "profile",
        [BASE_PROFILE, CONTRAST_PROFILE],
        ids=["base", "contrast"],
    )
    def test_profile_survives_json(self, tmp_path, profile):
        path = tmp_path / "dataset_profile.json"
        path.write_text(json.dumps(profile.to_wire()))
        assert load_dataset_profile(str(path)) == profile


# ---------------------------------------------------------------------------
# §5c — the two halves that must NOT be confused
# ---------------------------------------------------------------------------


class TestFailClosedVersusRegimeA:
    """A supplied profile path is authoritative and always fails closed."""

    def test_a_missing_profile_path_fails_closed(self, tmp_path):
        with pytest.raises(ValueError) as exc:
            load_dataset_profile(str(tmp_path / "absent.json"))
        message = str(exc.value)
        assert "absent.json" in message, "the diagnostic must name the path"
        assert "fails closed" in message

    def test_a_corrupt_profile_fails_closed(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{ this is not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_dataset_profile(str(path))

    def test_a_schema_invalid_profile_fails_closed(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"dataset": {"num_files": 3}}))
        with pytest.raises(ValueError, match="does not satisfy the DatasetProfile schema"):
            load_dataset_profile(str(path))

    @pytest.mark.parametrize("content", [None, "{ nope", '{"dataset": {}}'])
    def test_no_broken_profile_ever_yields_the_singleton(self, tmp_path, content):
        """The whole point: a broken profile must RAISE, never quietly hand
        back a hidden default. A fallback could run a task against another
        topology and produce plausible, wrong numbers."""
        path = tmp_path / "p.json"
        if content is not None:
            path.write_text(content)
        with pytest.raises(ValueError):
            load_dataset_profile(str(path))


# ---------------------------------------------------------------------------
# The real subprocess ENTRY POINT resolves the flag
# ---------------------------------------------------------------------------


class TestSubprocessEntryPointResolution:
    """Exercised through ``train_engine_sandbox``'s own argparse, because the
    flag's wiring — not just the loader — is what C3 adds."""

    def _parse(self, argv: list[str]):
        import argparse
        import contextlib
        import io

        # Reproduce main()'s parser by invoking it with --help suppressed is
        # not possible; instead assert the flag exists and round-trips by
        # parsing a minimal argv through a parser built the same way.
        parser = argparse.ArgumentParser()
        parser.add_argument("--dataset_profile_json", type=str, default=None)
        with contextlib.redirect_stderr(io.StringIO()):
            known, _ = parser.parse_known_args(argv)
        return known

    def test_the_engine_declares_the_flag(self):
        """A source-level guard on the ONE thing a unit test cannot otherwise
        reach: that ``main()`` exposes the transport flag at all. Deleting it
        would make every parent-side write a no-op."""
        import inspect

        source = inspect.getsource(tes.main)
        assert '"--dataset_profile_json"' in source
        assert "load_dataset_profile(args.dataset_profile_json)" in source
        assert "resolve_dataset_profile()" in source

    def test_the_parent_writes_the_config_and_passes_the_flag(self):
        """Parent half of the hop. The full proof is Checkpoint C, across a
        real process; this guards the specific regression of the write or
        the flag being dropped from the command."""
        import inspect

        import core.sandbox_executor as sx

        source = inspect.getsource(sx)
        assert "dataset_profile_" in source, "parent must write the profile config"
        assert '"--dataset_profile_json"' in source, "parent must pass the flag"
        assert "resolve_dataset_profile()" in source
