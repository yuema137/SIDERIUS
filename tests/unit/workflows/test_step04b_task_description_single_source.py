"""Step 04b — the task description has ONE runtime declaration.

Design: ``docs/design/generic_framework_upgrade/
step_04_candidate_creation_mechanics/pr_04b_task_description_single_source.md``
(§6 the 13.4-A rung, §7 Checkpoint C, §8 failure classes).

Before 04b, ``configs/task_config.yaml`` and ``configs/lit_review_config.yaml``
each declared a byte-identical ``task_description`` and the lit-review builder
read the second one. This module pins the collapse from three angles, each
naming a defect the others cannot see:

* **the declaration guard** — a second top-level declaration cannot silently
  reappear in ``configs/`` (failure class 1);
* **rung 13.4-A** — varying ONLY the canonical text moves the lit-review
  input, so the canonical source is genuinely the one being read rather than
  a duplicate that happens to agree (§6);
* **Checkpoint C** — the same variation survives all the way to the rendered
  prompt at the LLM boundary, through real production code with only the
  network stubbed (§7).

Why a sentinel rather than the shipped text: the two declarations were
byte-identical, so *any* assertion phrased against the TIDMAD description
passes just as happily whether the canonical source or the duplicate is
authoritative. Only a value that exists in exactly one of them discriminates.

No real LLM call is required or made — Gate 1 and Gate 2 are both NOT
REQUIRED for this PR (§10), and the recorder's clients raise on any attempt
to reach the network.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import DynamicSearchConfig
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review.ml_literature_review import MLLiteratureReviewAgent
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from workflows import task_config as tc
from workflows.model_exploration import _build_lit_review_input
from workflows.task_config import get_task_description, load_task_config

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIGS_DIR = REPO_ROOT / "configs"
TASK_CONFIG_YAML = CONFIGS_DIR / "task_config.yaml"
LIT_REVIEW_YAML = CONFIGS_DIR / "lit_review_config.yaml"

# A description that cannot be confused with the shipped TIDMAD one, in any
# substring direction.
ALT_TASK = "ALT-TASK-04B: transcribe medieval lute tablature from scanned manuscripts."

# The markdown headings the three lit-review prompt families render the
# {TASK_DESCRIPTION} placeholder under. Residue assertions are scoped to these
# blocks: the surrounding prompt prose legitimately contains task-flavoured
# vocabulary, so a whole-prompt absence assertion would be a test-design error
# (design §6).
_TASK_BLOCK_HEADINGS = (
    "The task the research agent is working on",  # search-decision
    "The task the proposer is working on",  # synthesis
    "Downstream task context",  # paper-extract
)


@pytest.fixture(autouse=True)
def _clear_task_config_cache():
    """``load_task_config`` memoizes per absolute path and returns a SHARED
    mutable dict. Tests here swap the file under a path, so the cache is
    dropped on both sides of every test."""
    tc._clear_cache_for_tests()
    yield
    tc._clear_cache_for_tests()


def _task_blocks(prompt: str) -> list[str]:
    """The bodies of the prompt's task-description sections.

    Splits on markdown ``## `` headings and returns the body of each section
    whose heading is one of the three the placeholder renders under.
    """
    blocks: list[str] = []
    for section in prompt.split("\n## "):
        heading, _, body = section.partition("\n")
        if heading.strip().lstrip("# ").strip() in _TASK_BLOCK_HEADINGS:
            blocks.append(body)
    return blocks


def _write_task_config_with(tmp_path: Path, description: str) -> Path:
    """The shipped task config with ONLY ``task_description`` replaced.

    Built by parsing the shipped file and substituting one key, so the rung
    cannot accidentally vary a second axis — the forward contract, the preset
    and every other declaration are carried across verbatim. Asserted, not
    assumed, by ``test_the_fixture_varies_only_the_description``.
    """
    raw = yaml.safe_load(TASK_CONFIG_YAML.read_text(encoding="utf-8"))
    raw["task_description"] = description
    configs = tmp_path / "configs"
    configs.mkdir(exist_ok=True)
    path = configs / "task_config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _interp() -> InterpretationOutput:
    return InterpretationOutput(
        take_home_message="stub",
        model_types=["wavenet"],
        model_descriptions={"wavenet": "d"},
        summaries=[],
        cumulative_information_gain=0.0,
        best_denoising_score=None,
        convergence_signal="no_history",
        iteration=1,
        total_experiments=1,
        key_findings=["kf1"],
        bottlenecks=["b1"],
    )


def _storage(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="r1"),
    )


_LLM_KWARGS = {
    "llm_provider": "openai",
    "llm_model_id": "m",
    "search_llm_provider": "",
    "search_llm_model_id": "",
}


# ---------------------------------------------------------------------------
# The declaration guard — failure class 1
# ---------------------------------------------------------------------------


class TestSingleSourceDeclarationGuard:
    """A second ``task_description`` authority cannot silently reappear.

    **Delete this class and the duplicate comes back unnoticed**: nothing else
    in the suite compares the two config files, and because they were
    byte-identical when the duplicate existed, every rendering test kept
    passing the whole time it was authoritative. That is precisely how the
    defect survived until Step 04b.
    """

    def _declaring_files(self) -> set[str]:
        """Config files whose PARSED top-level mapping declares the key.

        ``*.example.yaml`` is excluded, and the exclusion is narrow on
        purpose. ``configs/task_config.example.yaml`` is the copy-me template
        for the canonical file itself — ``cp configs/task_config.example.yaml
        configs/task_config.yaml`` — so it MUST declare the key; a template
        that omitted the required field would be a broken template. It is not
        a second authority because nothing loads it: the only references in
        executable source are remediation strings in ``workflows/task_config.py``
        (:56, :152) telling an operator which file to copy. Verified by grep at
        implementation time, and its own header states "the workflow uses
        configs/task_config.yaml at runtime, never this example file".

        Any NON-example config declaring the key is a real second authority
        and reds.
        """
        declaring: set[str] = set()
        for path in sorted(CONFIGS_DIR.rglob("*.yaml")) + sorted(CONFIGS_DIR.rglob("*.yml")):
            if path.name.endswith(".example.yaml") or path.name.endswith(".example.yml"):
                continue
            try:
                parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:  # pragma: no cover - a malformed config is another test's defect
                continue
            if isinstance(parsed, dict) and "task_description" in parsed:
                declaring.add(path.relative_to(CONFIGS_DIR).as_posix())
        return declaring

    def test_exactly_one_config_declares_the_task_description(self):
        assert self._declaring_files() == {"task_config.yaml"}, (
            "configs/ must contain EXACTLY ONE runtime top-level "
            "`task_description` declaration, in task_config.yaml. Found: "
            f"{sorted(self._declaring_files())}. A second declaration is a "
            "second authority: the copies start byte-identical, so nothing "
            "renders differently until they drift, and by then the wrong one "
            "may be the live value. Delete it and read the canonical source "
            "via get_task_description(load_task_config())."
        )

    def test_the_example_template_is_not_counted_but_does_declare_the_key(self):
        """Pins the exclusion above so it stays narrow and honest.

        Reds two ways: if the template loses its ``task_description`` (a
        broken copy-me template), or if the exclusion is ever widened into a
        blanket suffix skip that would also hide a real second authority.
        """
        example = CONFIGS_DIR / "task_config.example.yaml"
        parsed = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert "task_description" in parsed
        assert example.name not in self._declaring_files()

    def test_the_guard_reads_declarations_not_prose(self):
        """The negative control — and the reason this guard parses YAML.

        ``configs/lit_review_config.yaml`` legitimately *explains* in a
        comment where the description now lives, so its raw text contains the
        phrase while its parsed mapping declares nothing. A substring scan
        would red on that comment — including the one Step 04b itself wrote.
        """
        text = LIT_REVIEW_YAML.read_text(encoding="utf-8")
        assert "task_description" in text, (
            "expected the lit-review config to keep explaining where the "
            "description comes from — if that prose was deleted, this control "
            "no longer proves the guard ignores comments"
        )
        assert "lit_review_config.yaml" not in self._declaring_files()

    def test_the_canonical_declaration_still_exists(self):
        """Not zero sources. A guard that only forbade declarations would be
        satisfied by a repository that had lost the canonical one too."""
        parsed = yaml.safe_load(TASK_CONFIG_YAML.read_text(encoding="utf-8"))
        assert str(parsed.get("task_description") or "").strip() != ""


# ---------------------------------------------------------------------------
# Rung 13.4-A — lit-review half
# ---------------------------------------------------------------------------


class TestRung134ALitReviewHalf:
    """Vary ONLY the canonical task-description text; the lit-review input
    must follow it.

    Reds when the lit-review node still resolves the description from its own
    config — i.e. when the duplicate is authoritative again (design §6).
    """

    def test_the_fixture_varies_only_the_description(self, tmp_path):
        """Machine-check the changed axis before trusting the contrast.

        An atomicity claim asserted only in prose is how a two-axis contrast
        gets mistaken for a one-axis one.
        """
        shipped = yaml.safe_load(TASK_CONFIG_YAML.read_text(encoding="utf-8"))
        alt = yaml.safe_load(
            _write_task_config_with(tmp_path, ALT_TASK).read_text(encoding="utf-8")
        )
        assert alt["task_description"] == ALT_TASK
        assert alt["task_description"] != shipped["task_description"]

        stripped_shipped = copy.deepcopy(shipped)
        stripped_alt = copy.deepcopy(alt)
        del stripped_shipped["task_description"], stripped_alt["task_description"]
        assert stripped_alt == stripped_shipped, (
            "the 13.4-A fixture varies a second axis — the contrast would no "
            "longer isolate the task description"
        )

    def test_the_lit_review_input_follows_the_canonical_source(self, tmp_path, monkeypatch):
        """The rung itself, driven through the REAL production builder.

        The lit-review config handed in is the SHIPPED one, parsed from disk —
        so this is the production pairing, not a synthetic dict chosen to make
        the point.
        """
        path = _write_task_config_with(tmp_path, ALT_TASK)
        shipped_lit_cfg = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))

        monkeypatch.setattr(tc, "_SIDERIUS_ROOT", str(tmp_path))  # F-SCANA-2 root redirection
        tc._clear_cache_for_tests()
        assert Path(tc.default_task_config_path()).resolve() == path.resolve()

        inp = _build_lit_review_input(
            shipped_lit_cfg,
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="r1",
        )
        assert inp.task_description == ALT_TASK, (
            "the lit-review input did not follow the canonical task "
            "description — the duplicate is authoritative again"
        )
        assert "SQUID" not in inp.task_description

    def test_a_stale_duplicate_in_the_lit_review_config_is_not_consulted(
        self, tmp_path, monkeypatch
    ):
        """The discriminating half of the rung.

        An operator's stale local copy carrying its own ``task_description``
        must lose to the canonical source, not win and not merge. Without this
        case, a builder that preferred the YAML and fell back to the canonical
        source would pass the test above whenever the YAML had no key.
        """
        _write_task_config_with(tmp_path, ALT_TASK)
        stale_cfg = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))
        stale_cfg["task_description"] = "STALE-LOCAL-COPY: this value must never be used."

        monkeypatch.setattr(tc, "_SIDERIUS_ROOT", str(tmp_path))
        tc._clear_cache_for_tests()

        inp = _build_lit_review_input(
            stale_cfg,
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="r1",
        )
        assert inp.task_description == ALT_TASK
        assert "STALE-LOCAL-COPY" not in inp.task_description


# ---------------------------------------------------------------------------
# Checkpoint C — deterministic production-path integration
# ---------------------------------------------------------------------------


class TestCheckpointCProductionPath:
    """canonical §13 config → real ``_build_lit_review_input`` → real
    ``MLLiteratureReviewAgent.run()`` → captured prompt at the LLM boundary.

    Every hop is production code. Only the LLM boundary is a recorder, whose
    OpenAI clients raise on access, so no network call is possible and none is
    needed (design §7 — Gate 1 is NOT REQUIRED).

    **Why this is not redundant with the rung above**: the rung stops at the
    validated input object. This proves the value survives the node's own
    threading (``run()`` assigns ``_task_description`` from the input and
    passes it to three separate render call sites) and actually reaches the
    bytes an LLM would receive. A regression that dropped the field between
    the input and the renderer would pass 13.4-A and fail here.
    """

    def _run_capture(self, tmp_path) -> BoundaryRecorderBridge:
        recorder = BoundaryRecorderBridge()
        shipped_lit_cfg = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))
        inp = _build_lit_review_input(
            {
                **shipped_lit_cfg,
                "root_papers": [],
                "dynamic_search": {"enabled": True, "max_rounds": 1, "escalation_allowed": False},
            },
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="r1",
        )
        assert inp.dynamic_search == DynamicSearchConfig(
            enabled=True, max_rounds=1, escalation_allowed=False
        )
        agent = MLLiteratureReviewAgent(
            bridge_factory=lambda **_: recorder,
            root_cache_dir=str(tmp_path / "cache"),
        )
        agent.run(inp)
        assert recorder.captures, (
            "the boundary recorder never fired — the production path did not "
            "reach a prompt render, so this checkpoint proved nothing"
        )
        return recorder

    def test_the_shipped_task_reaches_the_rendered_prompt(self, tmp_path):
        """Under the shipped TIDMAD profile, the canonical text is what the
        LLM boundary sees. (`pb9_*` owns the byte-exactness of these prompts;
        this owns where the text came from.)"""
        canonical = get_task_description(load_task_config(str(TASK_CONFIG_YAML)))
        recorder = self._run_capture(tmp_path)

        blocks = [b for _, _, system, _ in recorder.captures for b in _task_blocks(system)]
        assert blocks, "no capture rendered a task-description block"
        for block in blocks:
            assert canonical in block

    def test_the_rendered_prompt_FOLLOWS_the_canonical_source(self, tmp_path, monkeypatch):
        """The discriminating assertion.

        A node still sourcing the description from the lit-review YAML — or a
        renderer emitting a literal — would produce the TIDMAD text here
        regardless of what the canonical config says. Residue is asserted
        against the task block only, never the whole prompt: the surrounding
        lit-review doctrine legitimately discusses denoising and 1-D signals.
        """
        _write_task_config_with(tmp_path, ALT_TASK)
        monkeypatch.setattr(tc, "_SIDERIUS_ROOT", str(tmp_path))
        tc._clear_cache_for_tests()

        recorder = self._run_capture(tmp_path)
        blocks = [b for _, _, system, _ in recorder.captures for b in _task_blocks(system)]
        assert blocks, "no capture rendered a task-description block"
        for block in blocks:
            assert ALT_TASK in block
            assert "SQUID" not in block, (
                "the shipped TIDMAD description survived in the task block "
                "while the canonical source declared something else — the "
                "lit-review path is not reading the canonical source"
            )
