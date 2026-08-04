"""The checkpoint load must leave no reserved pool behind on the device.

This is the measurement that motivated the fix, reduced to something a
test can run. It needs a real CUDA device and is skipped without one.

WHAT IT PINS. `torch.load(..., map_location=<cuda>)` materialises a second
full set of parameter tensors on the device. `load_state_dict` copies them
in, the temporary dict is freed -- and the caching allocator **keeps the
freed segments reserved**. Driver-visible memory counts reserved, not
allocated, so the process carries that pool for the rest of its life.

Observed on a V20 PR C2 lifecycle trace (punet, 216.9 MiB checkpoint),
immediately after the load:

```text
allocator reserved   236 -> 464 MiB   (+228)
allocator allocated  218 -> 218 MiB   (unchanged)
```

which left formal inference 208 MiB above an otherwise byte-identical
process that loads no checkpoint -- the two agreed to the MiB at every
earlier milestone.

WHY BOTH ROUTES RUN HERE. Asserting only that the host-side load is cheap
would pass on a build where the allocator behaved differently for
unrelated reasons. Running the device-side load in the same process, on
the same checkpoint, and requiring it to be the expensive one makes the
comparison the evidence rather than the threshold.
"""

from __future__ import annotations

import pytest
import torch

pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(), reason="the reserved-pool behaviour is a CUDA allocator property"
)

_MIB = 1024 * 1024

#: Large enough that a second copy clears allocator granularity by a wide
#: margin, small enough to run anywhere: 4096x4096 float32 = 64 MiB, and
#: the model holds two of them.
_WIDTH = 4096


def _model() -> torch.nn.Module:
    torch.manual_seed(20260803)
    return torch.nn.Sequential(
        torch.nn.Linear(_WIDTH, _WIDTH, bias=False),
        torch.nn.Linear(_WIDTH, _WIDTH, bias=False),
    )


def _checkpoint_mib() -> float:
    return (2 * _WIDTH * _WIDTH * 4) / _MIB


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "model.pth"
    torch.save(_model().state_dict(), path)
    return path


def _reserved_growth_around_load(checkpoint, map_location) -> tuple[float, float]:
    """Reserved and allocated growth, in MiB, across one checkpoint load.

    The model is already resident and the peak is reset first, so what is
    measured is the load and nothing else.
    """
    model = _model().cuda()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()  # settle the pool BEFORE measuring, never after
    before_reserved = torch.cuda.memory_reserved() / _MIB
    before_allocated = torch.cuda.memory_allocated() / _MIB

    state_dict = torch.load(checkpoint, map_location=map_location)
    model.load_state_dict(state_dict)
    del state_dict
    torch.cuda.synchronize()

    growth = (
        torch.cuda.memory_reserved() / _MIB - before_reserved,
        torch.cuda.memory_allocated() / _MIB - before_allocated,
    )
    del model
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    return growth


class TestTheHostSideLoadLeavesNoPoolBehind:
    def test_the_device_side_load_is_the_expensive_one(self, checkpoint):
        """The defect, reproduced. Without this the next test could pass
        for reasons having nothing to do with the fix."""
        reserved, allocated = _reserved_growth_around_load(checkpoint, torch.device("cuda:0"))
        assert reserved >= _checkpoint_mib() * 0.8, (
            f"expected the device-side load to strand ~{_checkpoint_mib():.0f} MiB of "
            f"reserved pool, saw {reserved:.0f} MiB"
        )
        # The parameters were copied INTO the model, so nothing extra
        # stays allocated -- which is exactly why `allocated` cannot see
        # this defect and `reserved` can.
        assert allocated < _checkpoint_mib() * 0.5

    def test_the_host_side_load_strands_nothing(self, checkpoint):
        """The fix. Restoring `map_location=<cuda>` in production fails
        the structural test; this one pins the property that matters."""
        reserved, allocated = _reserved_growth_around_load(checkpoint, "cpu")
        assert reserved < _checkpoint_mib() * 0.25, (
            f"the host-side load still grew the reserved pool by {reserved:.0f} MiB; "
            f"the checkpoint is {_checkpoint_mib():.0f} MiB"
        )
        assert allocated < _checkpoint_mib() * 0.5

    def test_the_host_route_is_cheaper_by_about_a_checkpoint(self, checkpoint):
        """The comparison, in one assertion: same process, same file, the
        only difference being where it was read."""
        device_side, _ = _reserved_growth_around_load(checkpoint, torch.device("cuda:0"))
        host_side, _ = _reserved_growth_around_load(checkpoint, "cpu")
        assert device_side - host_side >= _checkpoint_mib() * 0.8


class TestTheWeightsStillArrive:
    def test_values_match_the_device_side_load_exactly(self, checkpoint):
        """Memory is not bought with a partial load."""
        reference = _model().cuda()
        reference.load_state_dict(torch.load(checkpoint, map_location=torch.device("cuda:0")))

        subject = _model().cuda()
        state_dict = torch.load(checkpoint, map_location="cpu")
        subject.load_state_dict(state_dict)
        del state_dict

        # strict=True on purpose: a differing number of entries would let a
        # zip silently compare only the shorter prefix and pass.
        for a, b in zip(
            reference.state_dict().values(), subject.state_dict().values(), strict=True
        ):
            assert torch.equal(a, b)

    def test_the_parameters_stay_on_the_device(self, checkpoint):
        """`load_state_dict` copies into the resident parameters; a model
        dragged back to the host would still be numerically right and
        would run every forward in the wrong place."""
        model = _model().cuda()
        model.load_state_dict(torch.load(checkpoint, map_location="cpu"))
        for param in model.parameters():
            assert param.is_cuda
            assert param.dtype == torch.float32
