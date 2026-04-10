"""Smoke tests for the recording test doubles in ``tests/helpers/``.

These are *infrastructure* tests — every pseudo-mode test in the project will
depend on the recording fakes working correctly, so we verify them explicitly
here. If this file passes, the recording fakes are safe to build
pseudo-full-loop tests on.

Coverage:

* ``RecordingLLMBridge``: drop-in compat, predefined-response delivery, calls
  list ordering, FIFO queue semantics, loud failure on queue exhaustion,
  ``for_agent`` classmethod loading from ``PSEUDO_DATA_ROOT``.
* ``RecordingSandbox``: real directory creation under ``tmp_path``, stub
  anchor map, predefined ``execute_*`` results with disk-mirroring,
  ``save_record`` in-memory + on-disk persistence, calls list captures
  attempted invocations even when the queue is exhausted, ``for_model``
  classmethod loading from ``PSEUDO_DATA_ROOT``.
* ``load_pseudo_data``: directory-to-dict loading semantics.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.helpers import _pseudo_data
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox


# =====================================================================
# RecordingLLMBridge
# =====================================================================

class TestRecordingLLMBridge:

    def test_drop_in_init_swallows_real_bridge_kwargs(self):
        """The bridge accepts and silently ignores real-LLMBridge constructor
        params so the agent can call ``self._bridge_factory(**real_kwargs)``
        without test-side translation."""
        bridge = RecordingLLMBridge(
            responses={"generate": {"action": "PUNET"}},
            # Real-bridge kwargs that should be silently swallowed:
            provider="gemini",
            model_id="gemini-3.1-pro-preview",
            reflect_provider="gemini",
            reflect_model_id="gemini-2.5-flash",
            base_url="http://nowhere.test",
        )
        assert bridge.generate("sys", "user") == {"action": "PUNET"}

    def test_generate_returns_predefined_dict(self):
        bridge = RecordingLLMBridge(responses={
            "generate": {"action": "PUNET", "model_config": {"width": 32}},
        })
        out = bridge.generate("system prompt", "user prompt")
        assert out == {"action": "PUNET", "model_config": {"width": 32}}

    def test_calls_list_records_invocations_in_order(self):
        bridge = RecordingLLMBridge(responses={
            "generate": {"action": "PUNET"},
            "reflect":  {"conclusion": "good"},
        })
        bridge.generate("sys1", "user1")
        bridge.reflect("exp_001", "hypo", {"loss": 0.5}, {"baseline": 1.0})

        assert len(bridge.calls) == 2
        assert bridge.calls[0] == ("generate", "sys1", "user1")
        assert bridge.calls[1] == (
            "reflect", "exp_001", "hypo", {"loss": 0.5}, {"baseline": 1.0},
        )

    def test_fifo_queue_returns_responses_in_order(self):
        bridge = RecordingLLMBridge(responses={
            "generate": [{"a": 1}, {"a": 2}, {"a": 3}],
        })
        assert bridge.generate("s", "u") == {"a": 1}
        assert bridge.generate("s", "u") == {"a": 2}
        assert bridge.generate("s", "u") == {"a": 3}

    def test_queue_exhaustion_raises_runtime_error_with_diagnostic(self):
        bridge = RecordingLLMBridge(responses={"generate": {"action": "PUNET"}})
        bridge.generate("s", "u")
        with pytest.raises(RuntimeError) as exc_info:
            bridge.generate("s", "u")
        msg = str(exc_info.value)
        assert "no canned response" in msg
        assert "generate" in msg
        assert "Total calls so far" in msg

    def test_unregistered_method_raises(self):
        """Calling reflect when only generate was registered raises immediately."""
        bridge = RecordingLLMBridge(responses={"generate": {"action": "PUNET"}})
        with pytest.raises(RuntimeError, match="no canned response"):
            bridge.reflect("e", "h", {}, {})

    def test_for_agent_loads_from_pseudo_data_root(self, tmp_path, monkeypatch):
        """``for_agent`` reads every ``*.json`` file under
        ``PSEUDO_DATA_ROOT/api_call_outputs/{name}/`` and uses each file's
        stem as the method name."""
        agent_dir = tmp_path / "api_call_outputs" / "fake_agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "generate.json").write_text(json.dumps({"action": "FAKE"}))
        (agent_dir / "reflect.json").write_text(json.dumps({"conclusion": "fake"}))

        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        bridge = RecordingLLMBridge.for_agent("fake_agent")
        assert bridge.generate("s", "u") == {"action": "FAKE"}
        assert bridge.reflect("e", "h", {}, {}) == {"conclusion": "fake"}

    def test_for_agent_raises_on_missing_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        with pytest.raises(FileNotFoundError, match="No pseudo_data directory"):
            RecordingLLMBridge.for_agent("does_not_exist")


# =====================================================================
# RecordingSandbox
# =====================================================================

class TestRecordingSandbox:

    def test_drop_in_init_creates_real_directories(self, tmp_path):
        sb = RecordingSandbox(base_dir=str(tmp_path), run_name="test_run")
        for key in ("configs", "models", "records", "data"):
            assert os.path.isdir(sb.dirs[key]), f"{key} dir not created at {sb.dirs[key]}"

    def test_drop_in_init_swallows_real_sandbox_kwargs(self, tmp_path):
        """``file_index``, ``progress_bar`` are real-sandbox constructor params
        that the recording sandbox should silently ignore."""
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            file_index=6,
            progress_bar=False,
        )
        # If __init__ raised on the unknown kwargs, we'd never get here
        assert os.path.isdir(sb.dirs["configs"])

    def test_stub_anchor_map_is_written_and_parseable(self, tmp_path):
        sb = RecordingSandbox(base_dir=str(tmp_path))
        anchor_path = os.path.join(sb.dirs["data"], "segment_anchors.json")
        assert os.path.exists(anchor_path)
        with open(anchor_path) as f:
            stub = json.load(f)
        assert "anchors" in stub
        assert "s_max" in stub

    def test_execute_training_returns_canned_and_writes_to_disk(self, tmp_path):
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            canned={"execute_training": {
                "status": "success",
                "results": {"final_loss": 0.42, "model_params": 12345},
            }},
        )
        result = sb.execute_training(
            exp_id="exp_001", run_name="rn", model_type="punet",
            m_cfg={"width": 32}, t_cfg={"lr": 1e-3}, l_cfg={"loss_type": "focal"},
        )
        # Returned dict matches the canned value
        assert result["results"]["final_loss"] == 0.42

        # AND a real file was written to the same path the real subprocess would
        result_path = os.path.join(
            sb.dirs["records"], "rn", "experiment_results_punet_exp_001.json",
        )
        assert os.path.exists(result_path)
        with open(result_path) as f:
            on_disk = json.load(f)
        assert on_disk["final_loss"] == 0.42

    def test_execute_scoring_returns_canned_and_writes_to_disk(self, tmp_path):
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            canned={"execute_scoring": {
                "status": "success",
                "results": {"denoising_score": 0.69, "file_vector": [0.5] * 20},
            }},
        )
        result = sb.execute_scoring(exp_id="exp_001", run_name="rn", model_type="punet")
        assert result["results"]["denoising_score"] == 0.69

        score_path = os.path.join(
            sb.dirs["records"], "rn", "score_results_punet_exp_001.json",
        )
        assert os.path.exists(score_path)

    def test_save_record_appends_to_in_memory_list(self, tmp_path):
        sb = RecordingSandbox(base_dir=str(tmp_path))
        sb.save_record({"exp_id": "e1", "denoising_score": 0.5})
        sb.save_record({"exp_id": "e2", "denoising_score": 0.7})
        assert len(sb.saved_records) == 2
        assert sb.saved_records[0]["exp_id"] == "e1"
        assert sb.saved_records[1]["exp_id"] == "e2"

    def test_save_record_writes_summary_file_and_appends_across_calls(self, tmp_path):
        sb = RecordingSandbox(base_dir=str(tmp_path), run_name="my_run")
        sb.save_record({"exp_id": "e1"})
        sb.save_record({"exp_id": "e2"})
        sb.save_record({"exp_id": "e3"})

        summary_path = os.path.join(str(tmp_path), "summary_my_run.json")
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert [r["exp_id"] for r in summary] == ["e1", "e2", "e3"]

    def test_calls_list_records_attempts_even_on_queue_exhaustion(self, tmp_path):
        """The call tuple is appended to ``self.calls`` BEFORE ``_pop`` raises,
        so a call that exhausted the queue still shows up in the assertion list.
        Helps debug 'why is the agent calling this method one more time than I
        registered for?'"""
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            canned={"execute_training": {"status": "success", "results": {}}},
        )
        sb.execute_training(
            exp_id="e1", run_name="rn", model_type="punet",
            m_cfg={}, t_cfg={}, l_cfg={},
        )
        with pytest.raises(RuntimeError):
            sb.execute_training(
                exp_id="e2", run_name="rn", model_type="punet",
                m_cfg={}, t_cfg={}, l_cfg={},
            )
        methods = [c[0] for c in sb.calls]
        assert methods == ["execute_training", "execute_training"]

    def test_for_model_loads_from_pseudo_data_root(self, tmp_path, monkeypatch):
        model_dir = tmp_path / "train_outputs" / "fake_model"
        model_dir.mkdir(parents=True)
        (model_dir / "execute_training.json").write_text(
            json.dumps({"status": "success", "results": {"final_loss": 0.1}})
        )
        (model_dir / "execute_scoring.json").write_text(
            json.dumps({"status": "success", "results": {"denoising_score": 0.9}})
        )

        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        sb = RecordingSandbox.for_model(
            "fake_model",
            base_dir=str(tmp_path / "sb_root"),
        )
        result = sb.execute_training(
            exp_id="e1", run_name="rn", model_type="fake_model",
            m_cfg={}, t_cfg={}, l_cfg={},
        )
        assert result["results"]["final_loss"] == 0.1

        score = sb.execute_scoring(exp_id="e1", run_name="rn", model_type="fake_model")
        assert score["results"]["denoising_score"] == 0.9


# =====================================================================
# load_pseudo_data
# =====================================================================

class TestLoadPseudoData:

    def test_returns_dict_keyed_by_file_stem(self, tmp_path, monkeypatch):
        agent_dir = tmp_path / "api_call_outputs" / "agent_x"
        agent_dir.mkdir(parents=True)
        (agent_dir / "alpha.json").write_text(json.dumps({"x": 1}))
        (agent_dir / "beta.json").write_text(json.dumps({"y": 2}))

        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        result = _pseudo_data.load_pseudo_data("api_call_outputs", "agent_x")
        assert result == {"alpha": {"x": 1}, "beta": {"y": 2}}

    def test_raises_on_missing_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        with pytest.raises(FileNotFoundError, match="No pseudo_data directory"):
            _pseudo_data.load_pseudo_data("api_call_outputs", "does_not_exist")

    def test_returns_empty_dict_for_empty_directory(self, tmp_path, monkeypatch):
        agent_dir = tmp_path / "api_call_outputs" / "empty_agent"
        agent_dir.mkdir(parents=True)
        monkeypatch.setattr(_pseudo_data, "PSEUDO_DATA_ROOT", tmp_path)
        result = _pseudo_data.load_pseudo_data("api_call_outputs", "empty_agent")
        assert result == {}
