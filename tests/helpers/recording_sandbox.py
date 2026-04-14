"""``RecordingSandbox`` — drop-in test double for ``core.sandbox_executor.TidmadSandbox``.

Mimics the real sandbox's persistence behavior as faithfully as possible:
real directories on disk under a pytest ``tmp_path``, real JSON files written
by ``save_record``, real result files written by ``execute_training`` /
``execute_scoring``. The only thing skipped is the actual subprocess
execution (training, inference, scoring) — those return predefined dicts
directly instead of running ``train_engine_sandbox.py`` or any other
subprocess.

Design principles (see ``docs/pseudo_test_infra.md`` §4B):
  * Drop-in: ``__init__`` accepts ``**kwargs`` so the agent's
    ``self._sandbox_factory(...)`` call works without test-side translation.
  * Real filesystem fidelity: directories actually exist on disk under
    ``base_dir`` (typically pytest's ``tmp_path``). A stub
    ``segment_anchors.json`` is written so the tuner agent's anchor map
    check passes without special-casing.
  * Predefined results are plain post-call dicts shaped exactly like the
    real ``TidmadSandbox.execute_*()`` returns. Per-method FIFO queue,
    loud failure on exhaustion.
  * ``save_record`` keeps an in-memory list (``saved_records``) for fast
    test assertions AND writes to the same ``summary_{run_name}.json`` path
    the real sandbox uses, so any code that reads it back works.
  * Public ``calls`` and ``saved_records`` lists for direct test
    inspection. No helper methods.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from tests.helpers._pseudo_data import load_pseudo_data


class RecordingSandbox:
    """Test double for :class:`core.sandbox_executor.TidmadSandbox`.

    Attributes:
        base_dir: root directory for all on-disk artifacts (typically a
            pytest ``tmp_path``). Real directories are created under it
            in ``__init__``.
        run_name: the run identifier used to scope per-run subdirectories.
        dirs: dict mirroring :attr:`TidmadSandbox.dirs`. Every entry is a
            real directory that exists on disk. Includes ``"configs"``,
            ``"models"``, ``"records"``, ``"data"``.
        calls: list of recorded method invocations. Each entry is a tuple
            ``(method_name, *positional_args)``. Tests inspect this directly
            to assert on what configs were passed to training, what model
            type was scored, etc.
        saved_records: list of every record passed to ``save_record``, in
            the order they were saved. Tests inspect this directly to verify
            the orchestration assembled the right record.
    """

    def __init__(
        self,
        base_dir: str,
        run_name: str = "test",
        canned: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        # **kwargs accepts (and silently ignores) the real TidmadSandbox
        # constructor parameters: file_index, progress_bar, etc. Drop-in
        # replacement so the agent's sandbox_factory(...) call works
        # without test-side translation.
        self.base_dir = base_dir
        self.run_name = run_name
        self.dirs: Dict[str, str] = {
            "configs": os.path.join(base_dir, "configs", run_name),
            "models":  os.path.join(base_dir, "cached_models"),
            "records": os.path.join(base_dir, "records"),
            "data":    os.path.join(base_dir, "data"),
        }
        for path in self.dirs.values():
            os.makedirs(path, exist_ok=True)

        # Stub segment_anchors.json so the tuner agent's
        # ``load_anchor_map(sandbox.dirs["data"]/segment_anchors.json)``
        # check at ml_hyperparameter_tune_agent.py:160 passes. The actual
        # canned scoring result is what drives the test, not the real
        # anchor data — this stub only needs to be a parseable file with
        # the minimum valid shape.
        stub_anchors = {"anchors": {"0": {"0": 1.0}}, "s_max": 1.0}
        with open(os.path.join(self.dirs["data"], "segment_anchors.json"), "w") as f:
            json.dump(stub_anchors, f)

        # Per-method FIFO queue of predefined results
        self._queues: Dict[str, List[Any]] = {}
        for method, value in (canned or {}).items():
            self._queues[method] = list(value) if isinstance(value, list) else [value]

        # Public attributes for test assertions
        self.calls: List[Tuple[Any, ...]] = []
        self.saved_records: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Subprocess-execution methods (mirror TidmadSandbox)
    # ------------------------------------------------------------------

    def score_vector(self, sample_set, anchor_map: dict, s_max: float,
                     denoised_filename_fn, **kwargs):
        """Mirror of :meth:`TidmadSandbox.score_vector`. Returns
        ``(file_vector, scalar)`` from the next predefined result."""
        self.calls.append(("score_vector",))
        result = self._pop("score_vector")
        return result["file_vector"], result["scalar"]

    def execute_training(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: Dict[str, Any],
        t_cfg: Dict[str, Any],
        l_cfg: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Mirror of :meth:`TidmadSandbox.execute_training`. Returns the next
        predefined result and ALSO writes it to the same disk path the real
        subprocess would have written, so any code that reads it back works
        exactly like real mode.
        """
        self.calls.append(("execute_training", exp_id, model_type, m_cfg, t_cfg, l_cfg))
        result = self._pop("execute_training")

        result_dir = os.path.join(self.dirs["records"], run_name)
        os.makedirs(result_dir, exist_ok=True)
        result_path = os.path.join(
            result_dir, f"experiment_results_{model_type}_{exp_id}.json"
        )
        with open(result_path, "w") as f:
            json.dump(result.get("results", {}), f)
        return result

    def execute_inference(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: Dict[str, Any],
        l_cfg: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Mirror of :meth:`TidmadSandbox.execute_inference`. Returns the
        next predefined result. Real inference produces ``.h5`` denoised
        files; we skip writing those because scoring is also predefined and
        nothing reads them. A future test can write its own stubs if it
        specifically wants to exercise the file-existence path.
        """
        self.calls.append(("execute_inference", exp_id, model_type))
        return self._pop("execute_inference")

    def execute_scoring(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Mirror of :meth:`TidmadSandbox.execute_scoring`. Returns the next
        predefined result and writes it to the same disk path the real
        scoring subprocess would have written.
        """
        self.calls.append(("execute_scoring", exp_id, model_type))
        result = self._pop("execute_scoring")

        result_dir = os.path.join(self.dirs["records"], run_name)
        os.makedirs(result_dir, exist_ok=True)
        score_path = os.path.join(
            result_dir, f"score_results_{model_type}_{exp_id}.json"
        )
        with open(score_path, "w") as f:
            json.dump(result.get("results", {}), f)
        return result

    # ------------------------------------------------------------------
    # Persistence (mirror TidmadSandbox.save_record)
    # ------------------------------------------------------------------

    def get_summary(self) -> List[Dict[str, Any]]:
        """Mirror of :meth:`TidmadSandbox.get_summary`. Returns all records
        saved so far, in order. Reads from the in-memory list (identical to
        what's on disk in ``summary_{run_name}.json``)."""
        return list(self.saved_records)

    def save_record(self, record: Dict[str, Any]) -> None:
        """Mirror of :meth:`TidmadSandbox.save_record`. Appends to the
        in-memory ``saved_records`` list AND to the on-disk
        ``summary_{run_name}.json`` file (creating it if absent), exactly
        like the real sandbox.
        """
        self.calls.append(("save_record", record.get("exp_id", "<unknown>")))
        self.saved_records.append(record)

        summary_path = os.path.join(self.base_dir, f"summary_{self.run_name}.json")
        existing: List[Dict[str, Any]] = []
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []
        existing.append(record)
        with open(summary_path, "w") as f:
            json.dump(existing, f, indent=2)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pop(self, method: str) -> Any:
        """Pop and return the next predefined result for ``method``.

        Raises ``RuntimeError`` on queue exhaustion. Loud failure is
        intentional — silent fallback would mask test-setup bugs.
        """
        if not self._queues.get(method):
            raise RuntimeError(
                f"RecordingSandbox: no canned response left for {method!r}. "
                f"Registered methods: {sorted(self._queues.keys())}. "
                f"Total calls so far: {len(self.calls)}. "
                f"Did the test forget to register a result, or is the agent "
                f"making more subprocess calls than expected?"
            )
        return self._queues[method].pop(0)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def for_model(
        cls,
        model_type: str,
        base_dir: str,
        run_name: str = "test",
        **kwargs: Any,
    ) -> "RecordingSandbox":
        """Build a sandbox pre-loaded with canned outputs for a built-in model.

        Loads every ``*.json`` file under
        ``tests/pseudo_data/train_outputs/{model_type}/`` and uses each file's
        stem as the method name. For example, files ``execute_training.json``,
        ``execute_inference.json``, and ``execute_scoring.json`` produce a
        sandbox whose corresponding methods return the parsed contents of
        those files (one per call, FIFO).

        Args:
            model_type: built-in model key, e.g. ``"punet"``, ``"wavenet"``.
            base_dir: root directory for on-disk artifacts. Pass a pytest
                ``tmp_path`` so cleanup is automatic.
            run_name: run identifier scoping the per-run subdirectories.

        Raises:
            FileNotFoundError: if no pseudo-data directory exists for the
                given model. See ``docs/pseudo_test_infra.md`` for the
                directory layout.
        """
        canned = load_pseudo_data("train_outputs", model_type)
        return cls(base_dir=base_dir, run_name=run_name, canned=canned, **kwargs)
