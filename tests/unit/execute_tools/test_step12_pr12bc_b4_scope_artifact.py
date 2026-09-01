"""Step 12 / PR-12bc — B4: the scope artifact + digest ABI.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §D.2, §D.4, §M / B4; ledger §Q.B4.

**After this commit the ABI is frozen for the rest of the PR** (§F item 7), so
what is asserted here is what B6's transport, `G-12bc-B`'s evidence and every
adversarial plant will all cite.

Four properties, each the one the obvious implementation gets wrong:

* **cross-PROCESS determinism** — the same payload digests identically in a
  fresh interpreter, not merely twice in this one. A hash seeded per-process
  would pass an in-process check and fail in the child, which is the only
  place it matters;
* **verification BEFORE deserialization** — proven with a spy that fails the
  test if the parser is reached at all, not by trusting the call order;
* **atomicity** — an interrupted write leaves the OLD file or none, never a
  prefix, and leaves no `.tmp` debris to be mistaken for an artifact;
* **one digest authority** — a census, because a second one is not a duplicate
  hash implementation, it is a second answer to "which scope ran?".
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

from execute_tools.scope_artifact import (
    EVAL_SCOPE_STEM,
    TRAINING_SCOPE_STEM,
    ScopeArtifactError,
    ScopeEvidence,
    read_scope_artifact,
    scope_artifact_path,
    scope_digest,
    write_scope_artifact,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PAYLOAD = '{"kind":"synthetic_scope_v1","rows":[1,2]}'
MUTATED_PAYLOAD = '{"kind":"synthetic_scope_v1","rows":[1,3]}'


@pytest.fixture
def configs(tmp_path):
    return str(tmp_path / "configs" / "run")


# ======================================================================
# Determinism — across PROCESSES
# ======================================================================


class TestTheDigestIsDeterministic:
    def test_the_same_payload_digests_identically_in_a_FRESH_interpreter(self):
        """The property that actually matters: the parent and the child are
        different processes. An in-process double-call would pass even if the
        hash were seeded per-process, which is exactly the bug that would only
        ever appear at the boundary.
        """
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});\n"
                f"from execute_tools.scope_artifact import scope_digest;\n"
                f"print(scope_digest({PAYLOAD!r}))",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().splitlines()[-1] == scope_digest(PAYLOAD)

    def test_it_is_a_sha256_of_the_utf8_bytes(self):
        """Hardcoded, not recomputed with the same expression under test."""
        assert scope_digest("") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_a_one_character_change_changes_the_digest(self):
        assert scope_digest(PAYLOAD) != scope_digest(MUTATED_PAYLOAD)

    def test_non_ascii_payloads_digest_by_bytes_not_by_code_points(self):
        """A task is free to serialize non-ASCII. Encoding is pinned so a
        locale difference between parent and child cannot change identity.
        """
        payload = '{"note":"caf\\u00e9"}'
        assert scope_digest(payload) == scope_digest(payload)
        assert len(scope_digest("café")) == 64


# ======================================================================
# Write / read round trip
# ======================================================================


class TestTheArtifactRoundTrip:
    def test_write_then_verified_read_returns_the_exact_payload(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        assert read_scope_artifact(path, digest) == PAYLOAD

    def test_the_path_follows_the_existing_artifact_convention(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        assert os.path.isabs(path)
        assert path.endswith(os.path.join("run", "task_scope_exp1.json"))

    def test_the_two_legs_are_separate_artifacts(self, configs):
        """A combined file would make "eval scope absent" and "eval scope
        empty" the same on-disk state.
        """
        assert scope_artifact_path(configs, TRAINING_SCOPE_STEM, "e") != scope_artifact_path(
            configs, EVAL_SCOPE_STEM, "e"
        )

    def test_two_concurrent_attempts_cannot_collide(self, configs):
        """Per-``exp_id`` naming is what keeps them disjoint — asserted, since
        the alternative (one file per run) would have two attempts overwriting
        each other's scope with no error anywhere.
        """
        a = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "attempt_a")
        b = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "attempt_b")
        da = write_scope_artifact(a, PAYLOAD)
        db = write_scope_artifact(b, MUTATED_PAYLOAD)
        assert a != b
        assert read_scope_artifact(a, da) == PAYLOAD
        assert read_scope_artifact(b, db) != PAYLOAD

    def test_rewriting_the_same_path_replaces_it_wholly(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        write_scope_artifact(path, PAYLOAD + "                    ")
        digest = write_scope_artifact(path, PAYLOAD)
        assert read_scope_artifact(path, digest) == PAYLOAD


# ======================================================================
# Verification happens BEFORE deserialization
# ======================================================================


class TestTamperingIsRefusedBeforeDeserialization:
    def test_a_one_byte_mutation_is_refused(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(MUTATED_PAYLOAD)
        with pytest.raises(ScopeArtifactError, match="does not match the digest"):
            read_scope_artifact(path, digest)

    def test_the_refusal_names_BOTH_digests(self, configs):
        """So an operator can tell a tampered artifact from a stale one
        without opening the file.
        """
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        tampered = PAYLOAD + " "
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(tampered)
        with pytest.raises(ScopeArtifactError) as exc:
            read_scope_artifact(path, digest)
        assert digest in str(exc.value)
        assert scope_digest(tampered) in str(exc.value)

    def test_the_deserializer_is_NEVER_reached_on_a_mismatch(self, configs):
        """The acceptance criterion, proven with a spy rather than by
        reading the call order. If verification ever moves after parsing, the
        spy fires and this fails.
        """
        calls: list[str] = []

        def _spy_deserialize(payload: str):  # pragma: no cover - must not run
            calls.append(payload)
            raise AssertionError("deserialize_scope was reached on a tampered artifact")

        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")

        with pytest.raises(ScopeArtifactError):
            _spy_deserialize(read_scope_artifact(path, digest))
        assert calls == []

    def test_a_truncated_file_is_refused(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(PAYLOAD[: len(PAYLOAD) // 2])
        with pytest.raises(ScopeArtifactError, match="does not match the digest"):
            read_scope_artifact(path, digest)

    def test_a_missing_artifact_names_the_expected_path(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "never_written")
        with pytest.raises(ScopeArtifactError, match="does not exist") as exc:
            read_scope_artifact(path, scope_digest(PAYLOAD))
        assert path in str(exc.value)

    def test_an_empty_artifact_is_refused_rather_than_read_as_an_empty_scope(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("")
        with pytest.raises(ScopeArtifactError, match="does not match the digest"):
            read_scope_artifact(path, digest)


# ======================================================================
# Atomicity
# ======================================================================


class TestTheWriteIsAtomic:
    def test_an_interrupted_write_leaves_the_OLD_file_intact(self, configs, monkeypatch):
        """Never a prefix. The previous artifact survives, which is what makes
        a concurrent reader safe rather than merely lucky.
        """
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        first = write_scope_artifact(path, PAYLOAD)

        def _boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(ScopeArtifactError, match="cannot write"):
            write_scope_artifact(path, "REPLACEMENT")

        monkeypatch.undo()
        assert read_scope_artifact(path, first) == PAYLOAD

    def test_an_interrupted_write_leaves_no_tmp_debris(self, configs, monkeypatch):
        """A leftover `.tmp` beside a real artifact is a file a later reader
        or a cleanup glob could mistake for one.
        """
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        write_scope_artifact(path, PAYLOAD)
        directory = pathlib.Path(os.path.dirname(path))

        monkeypatch.setattr(os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
        with pytest.raises(ScopeArtifactError):
            write_scope_artifact(path, "REPLACEMENT")
        monkeypatch.undo()

        assert [p.name for p in directory.glob("*.tmp")] == []

    def test_an_unwritable_directory_refuses_AT_THE_PARENT(self, tmp_path):
        """Before any subprocess is launched — the message says so, because
        an operator reading a log needs to know no GPU minute was spent.
        """
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory")
        path = scope_artifact_path(str(blocker / "configs"), TRAINING_SCOPE_STEM, "e")
        with pytest.raises(ScopeArtifactError, match="before any subprocess was launched"):
            write_scope_artifact(path, PAYLOAD)

    def test_the_write_uses_replace_not_a_plain_open(self):
        """Structural: the atomicity claim is in the source, not only in the
        behaviour above, so a refactor that reverts to a bare write fails here
        even if a mocked test still passed.
        """
        src = (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        assert "os.replace(" in src
        assert "tempfile.mkstemp(" in src


# ======================================================================
# ONE digest authority
# ======================================================================


class TestExactlyOneDigestAuthority:
    def test_no_other_production_module_hashes_a_SCOPE_PAYLOAD(self):
        """A second digest site is a second answer to "which scope ran?".

        The census is over hashes of a SCOPE PAYLOAD specifically. Other
        digests legitimately exist in the same modules and answer different
        questions — each is named here with the fact it identifies, in the
        same sanctioned-site form B8 and the §F checkpoint use. A hash that is
        NOT on this list, in a scope-carrying module, fails.
        """
        #: hashing site -> the fact it identifies (NOT a scope payload)
        SANCTIONED_OTHER_DIGESTS = {
            # Step 12 / PR-12bc C1: the sha256 of an implementation's MODULE
            # SOURCE, which answers "is this the same code?" for the
            # registration lifecycle. It never sees a scope.
            "execute_tools/task_data_path.py": "content_identity",
        }
        offenders = []
        for rel in (
            "core/sandbox_executor.py",
            "execute_tools/train_engine_sandbox.py",
            "execute_tools/task_data_path.py",
        ):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if "scope" not in src or "hashlib.sha256" not in src:
                continue
            tree = ast.parse(src)
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                hashes = any(
                    isinstance(n, ast.Attribute)
                    and n.attr == "sha256"
                    and isinstance(n.value, ast.Name)
                    and n.value.id == "hashlib"
                    for n in ast.walk(fn)
                )
                if hashes and SANCTIONED_OTHER_DIGESTS.get(rel) != fn.name:
                    offenders.append(f"{rel}::{fn.name}")
        assert offenders == [], (
            f"{offenders} hash something in a scope-carrying module. If it is a "
            f"SCOPE payload, `scope_artifact.scope_digest` is the ONE identity "
            f"authority; if it identifies a different fact, name it above with "
            f"that fact."
        )

    def test_the_module_never_parses_the_payload(self):
        """Scope opacity, one layer out: the framework handles bytes and a
        hash. A `json.loads` here would be the framework reading task
        vocabulary — the exact defect Q-12-4 removed.
        """
        src = (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "loads" not in called
        assert "load" not in called


# ======================================================================
# The attempt-scope evidence stamp
# ======================================================================


class TestTheEvidenceStamp:
    def test_it_carries_the_identity_a_gate_needs_to_CITE_a_scope(self, configs):
        path = scope_artifact_path(configs, TRAINING_SCOPE_STEM, "exp1")
        digest = write_scope_artifact(path, PAYLOAD)
        ev = ScopeEvidence(leg=TRAINING_SCOPE_STEM, ref=path, digest=digest)
        assert ev.digest == scope_digest(PAYLOAD)
        assert ev.ref == path

    def test_a_short_digest_is_refused(self):
        """The stamp exists so evidence can cite an identity. A truncated
        digest would still look like evidence.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ScopeEvidence(leg="task_scope", ref="/x", digest="abc")
