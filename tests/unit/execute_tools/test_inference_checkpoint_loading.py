"""Formal inference must load its checkpoint on the host, not the device.

`map_location=DEVICE` materialises a SECOND full set of parameter tensors
on the GPU before `load_state_dict` copies them into the model. The
temporary state dict is then freed -- but the CUDA caching allocator keeps
the freed segments **reserved**, and driver-visible memory counts reserved,
not allocated. The process then carries a checkpoint's worth of dead pool
for the rest of its life.

Measured on a V20 PR C2 lifecycle trace (punet, 216.9 MiB checkpoint),
immediately after the load:

```text
allocator reserved   236 -> 464 MiB   (+228)
allocator allocated  218 -> 218 MiB   (unchanged)
```

That +228 MiB persisted through the forward and left formal inference
**208 MiB above** an otherwise byte-identical process that loads no
checkpoint -- the two were equal to the MiB at every earlier milestone.

These tests are about the two things that could go wrong with the fix:
the load could stop being host-side (the defect returns), or it could
change what is loaded (a correctness regression in exchange for memory).
The allocator proof itself needs a real GPU and lives in
`tests/integration/execute_tools/test_inference_checkpoint_memory.py`.
"""

from __future__ import annotations

import ast
import gc
import weakref
from pathlib import Path

import pytest
import torch

_INFERENCE_SOURCE = (
    Path(__file__).resolve().parents[3] / "src/execute_tools" / "inference_single.py"
)


def _main_function() -> ast.FunctionDef:
    tree = ast.parse(_INFERENCE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("main() not found in inference_single.py")


def _state_dict_load_call() -> ast.Call:
    """The `torch.load` that reads the agent-mode state dict.

    Located by its argument rather than by line, so the test survives
    edits above it. The fix-mode `torch.load(model_file, ...)` at the top
    of `main` loads a whole pickled model object and is a different call
    with different requirements -- it is deliberately not matched here.
    """
    for node in ast.walk(_main_function()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "load":
            continue
        first = node.args[0] if node.args else None
        if (
            isinstance(first, ast.Attribute)
            and first.attr == "model_path"
            and isinstance(first.value, ast.Name)
            and first.value.id == "args"
        ):
            return node
    raise AssertionError("no torch.load(args.model_path, ...) call found in main()")


class TestTheCheckpointIsReadOnTheHost:
    """The defect, as a source property."""

    def test_map_location_is_the_host(self):
        """`map_location=DEVICE` is the defect. Restoring it fails here."""
        call = _state_dict_load_call()
        by_name = {kw.arg: kw.value for kw in call.keywords}
        assert "map_location" in by_name, "the state-dict load must pin map_location explicitly"
        target = by_name["map_location"]
        assert isinstance(target, ast.Constant) and target.value == "cpu", (
            "the state dict must be read onto the host; loading it onto the device "
            "allocates a second parameter set whose freed blocks stay reserved"
        )

    def test_the_device_is_not_named_anywhere_in_that_call(self):
        """Guards the near-miss: `map_location=str(DEVICE)`, or DEVICE
        arriving through another keyword."""
        call = _state_dict_load_call()
        for node in ast.walk(call):
            assert not (isinstance(node, ast.Name) and node.id == "DEVICE"), (
                "DEVICE reached the state-dict load again"
            )

    def test_the_host_copy_is_released(self):
        """Without the release the host keeps a full parameter set alive
        for the whole inference run -- trading GPU pressure for host
        pressure is not the fix."""
        names = {
            target.id
            for node in ast.walk(_main_function())
            if isinstance(node, ast.Delete)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert "state_dict" in names

    def test_the_model_reaches_the_device_before_the_weights_load(self):
        """Why host-side loading is correct rather than merely cheaper:
        `load_state_dict` copies parameter-by-parameter INTO an already
        resident GPU model. If the load ran first, the copy target would
        be a host model and the transfer would happen afterwards anyway.
        """
        main = _main_function()
        transfer = max(
            node.lineno
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to"
            and any(isinstance(a, ast.Name) and a.id == "DEVICE" for a in node.args)
        )
        load = next(
            node.lineno
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_trained_state"
        )
        assert transfer < load

    def test_the_sentinel_preflight_still_runs_first(self):
        """A silent training crash must still surface as `error_training:`
        rather than as a FileNotFoundError on the .pth path."""
        main = _main_function()
        sentinel = next(
            node.lineno
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_assert_training_sentinel"
        )
        assert sentinel < _state_dict_load_call().lineno


class TestStrictnessIsUnchanged:
    """Memory is not bought with a weaker load."""

    def test_weights_only_is_not_weakened_for_the_state_dict(self):
        call = _state_dict_load_call()
        for kw in call.keywords:
            if kw.arg == "weights_only":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is True, (
                    "the state-dict load must not opt out of weights_only"
                )

    def test_load_state_dict_stays_strict(self):
        from ml_models.target_standardization import load_trained_state

        with pytest.raises(RuntimeError, match="Missing key"):
            load_trained_state(torch.nn.Linear(2, 1), {"weight": torch.zeros(1, 2)})


def _tiny_model() -> torch.nn.Module:
    torch.manual_seed(20260803)
    return torch.nn.Sequential(torch.nn.Linear(32, 64), torch.nn.ReLU(), torch.nn.Linear(64, 8))


DEVICES = ["cpu"] + (["cuda:0"] if torch.cuda.is_available() else [])


class TestWhatIsLoadedIsUnchanged:
    """The whole point is that only the *route* changes."""

    @pytest.mark.parametrize("device", DEVICES)
    def test_parameter_values_are_identical_either_way(self, tmp_path, device):
        source = _tiny_model()
        path = tmp_path / "model.pth"
        torch.save(source.state_dict(), path)

        device_side = _tiny_model().to(device)
        device_side.load_state_dict(torch.load(path, map_location=torch.device(device)))

        host_side = _tiny_model().to(device)
        state_dict = torch.load(path, map_location="cpu")
        host_side.load_state_dict(state_dict)
        del state_dict

        # strict=True on purpose: a differing number of entries would let a
        # zip silently compare only the shorter prefix and pass.
        for a, b in zip(
            device_side.state_dict().values(), host_side.state_dict().values(), strict=True
        ):
            assert torch.equal(a, b)

    @pytest.mark.parametrize("device", DEVICES)
    def test_predictions_are_identical_on_a_fixed_input(self, tmp_path, device):
        path = tmp_path / "model.pth"
        torch.save(_tiny_model().state_dict(), path)
        fixed = torch.arange(32, dtype=torch.float32).reshape(1, 32).to(device)

        device_side = _tiny_model().to(device).eval()
        device_side.load_state_dict(torch.load(path, map_location=torch.device(device)))

        host_side = _tiny_model().to(device).eval()
        host_side.load_state_dict(torch.load(path, map_location="cpu"))

        with torch.no_grad():
            assert torch.equal(device_side(fixed), host_side(fixed))

    @pytest.mark.parametrize("device", DEVICES)
    def test_dtype_and_device_placement_survive_the_host_load(self, tmp_path, device):
        """`load_state_dict` copies INTO the existing parameters, so the
        model must stay on its device in its dtype. A model silently
        dragged back to the host would still produce correct numbers and
        would run every forward in the wrong place."""
        path = tmp_path / "model.pth"
        torch.save(_tiny_model().state_dict(), path)
        model = _tiny_model().to(device)
        model.load_state_dict(torch.load(path, map_location="cpu"))
        for param in model.parameters():
            assert param.dtype == torch.float32
            assert param.device.type == torch.device(device).type

    def test_evaluation_mode_is_not_disturbed(self, tmp_path):
        path = tmp_path / "model.pth"
        torch.save(_tiny_model().state_dict(), path)
        model = _tiny_model()
        model.eval()
        model.load_state_dict(torch.load(path, map_location="cpu"))
        assert model.training is False


class TestFailureSemanticsAreUnchanged:
    def test_a_missing_checkpoint_still_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            torch.load(tmp_path / "absent.pth", map_location="cpu")

    def test_a_mismatched_checkpoint_still_raises(self, tmp_path):
        """Host-side loading must not turn a shape mismatch into a silent
        partial load."""
        path = tmp_path / "other.pth"
        torch.save(torch.nn.Linear(5, 5).state_dict(), path)
        with pytest.raises(RuntimeError):
            _tiny_model().load_state_dict(torch.load(path, map_location="cpu"))


class TestTheHostCopyDoesNotOutliveTheLoad:
    def test_the_state_dict_is_collectable_after_release(self, tmp_path):
        """Proves the release is real rather than decorative: if
        `load_state_dict` retained the loaded tensors, dropping the name
        would not free them and the host would hold two copies."""
        path = tmp_path / "model.pth"
        torch.save(_tiny_model().state_dict(), path)
        model = _tiny_model()

        state_dict = torch.load(path, map_location="cpu")
        first = next(iter(state_dict.values()))
        ref = weakref.ref(first)
        model.load_state_dict(state_dict)
        del state_dict, first
        gc.collect()

        assert ref() is None, "load_state_dict retained the checkpoint tensors"
