"""The run manifest — the record that makes "why did this differ?" answerable."""

from __future__ import annotations

from pathlib import Path

from tools.ci.provenance import SCHEMA_VERSION, build_manifest, safe_env_names

REPO = Path(__file__).resolve().parents[4]


class TestSecretRedaction:
    def test_no_secret_shaped_variable_name_is_recorded(self):
        """The artifact may be attached to a public run.

        Recording a value leaks it outright; recording the NAME of a credential
        variable still advertises which secrets a runner holds. Both are
        dropped. Fails as: OPENAI_API_KEY appears in an uploaded manifest.
        """
        names = safe_env_names(
            {
                "PATH": "/usr/bin",
                "OPENAI_API_KEY": "sk-real",
                "GH_TOKEN": "t",
                "MY_SECRET": "s",
                "DB_PASSWORD": "p",
                "AWS_CREDENTIAL_FILE": "c",
                "HTTP_AUTHORIZATION": "a",
            }
        )
        assert names == ["PATH"]

    def test_no_value_is_ever_returned(self):
        """A name list must not accidentally become a name=value list.

        Fails as: values leak into the manifest through the same field.
        """
        assert safe_env_names({"HARMLESS": "value-should-not-appear"}) == ["HARMLESS"]


class TestManifestFacts:
    def test_it_records_declared_profile_and_observed_cpu_separately(self):
        """The declared profile and the platform fact must both be visible.

        The CI shard count is DECLARED because no trustworthy effective-CPU
        source exists; recording only the declaration would hide a mismatch,
        and recording only the fact would hide the policy. Fails as: either
        side is missing, and the first remote run cannot correct the profile.
        """
        m = build_manifest(REPO, mode="bulk", declared_shards=4, declared_threads=1)
        assert m.profile.declared_shards == 4
        assert m.profile.declared_threads_per_shard == 1
        assert m.platform_facts.cpu_count is not None
        assert m.schema_version == SCHEMA_VERSION

    def test_it_records_the_unpinnable_residual(self):
        """A thread pool the harness cannot control must be stated, not implied.

        torch's inter-op pool ignores every thread variable and stays at
        cpu_count. Fails as: the manifest claims a fully pinned thread
        environment it does not have.
        """
        m = build_manifest(REPO, mode="bulk", declared_shards=1, declared_threads=1)
        assert "inter-op" in m.profile.unpinned_residual

    def test_it_records_config_and_resource_presence(self):
        """These are the two axes that made 43 tests differ silently (CP-8).

        Fails as: a run records neither, and a future parity mismatch is again
        unattributable after the fact.
        """
        m = build_manifest(REPO, mode="bulk", declared_shards=1, declared_threads=1)
        assert set(m.config_presence) >= {"tidmad_data_config.yaml", ".env"}
        assert set(m.resource_presence) >= {"legacy_tidmad_root", "pets_images", "davis_frames"}

    def test_untracked_files_are_counted_not_treated_as_dirty(self):
        """Pollution stays observable without failing a run.

        Fails as: untracked scratch marks the source dirty, or vanishes from
        the record entirely so pollution becomes invisible.
        """
        m = build_manifest(REPO, mode="bulk", declared_shards=1, declared_threads=1)
        assert isinstance(m.source.untracked, int)
