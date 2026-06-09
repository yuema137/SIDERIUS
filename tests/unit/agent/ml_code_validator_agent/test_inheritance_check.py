"""
Unit tests for Check #8: inherited component verification.

Tests _check_inherited_components() — the deterministic check that verifies
claimed architectural primitives actually appear in the generated code.
"""

import pytest

from nodes.ml_code_validator_agent import _check_inherited_components

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SAMPLE_VOCAB = [
    {"name": "dilated_causal_conv", "kind": "feature", "description": "...", "pattern": "dilation"},
    {
        "name": "gated_activation",
        "kind": "feature",
        "description": "...",
        "pattern": "sigmoid.*tanh|tanh.*sigmoid",
    },
    {
        "name": "skip_connection",
        "kind": "feature",
        "description": "...",
        "pattern": "skip|residual",
    },
    {
        "name": "spectral_conv",
        "kind": "feature",
        "description": "...",
        "pattern": "rfft|fft|spectral",
    },
    {"name": "receptive_field", "kind": "capability", "description": "...", "pattern": None},
    {
        "name": "embedding_layer",
        "kind": "feature",
        "description": "...",
        "pattern": "Embedding|nn\\.Embedding",
    },
]

WAVENET_LIKE_SOURCE = """
import torch
import torch.nn as nn

class DilatedBlock(nn.Module):
    def __init__(self, channels, dilation):
        super().__init__()
        self.conv = nn.Conv1d(channels, 2 * channels, kernel_size=3, dilation=dilation, padding=dilation)
        self.skip_proj = nn.Conv1d(channels, channels, 1)
        self.residual_proj = nn.Conv1d(channels, channels, 1)

    def forward(self, x):
        h = self.conv(x)
        h1, h2 = h.chunk(2, dim=1)
        z = torch.tanh(h1) * torch.sigmoid(h2)
        skip = self.skip_proj(z)
        residual = x + self.residual_proj(z)
        return residual, skip
"""

SIMPLE_CNN_SOURCE = """
import torch
import torch.nn as nn

class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv1d(1, 32, 3, padding=1)
        self.conv2 = nn.Conv1d(32, 256, 3, padding=1)

    def forward(self, x):
        x = torch.relu(self.conv1(x))
        return self.conv2(x)
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInheritanceCheck:
    def test_valid_claims_pass(self):
        """All claimed components found in source."""
        claims = [
            {
                "component": "dilated_causal_conv",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Core mechanism.",
            },
            {
                "component": "gated_activation",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Enables selective modulation.",
            },
            {
                "component": "skip_connection",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Gradient flow.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is True
        assert all("FOUND" in n for n in notes)

    def test_missing_component_fails(self):
        """Claiming spectral_conv but source has no FFT code."""
        claims = [
            {
                "component": "spectral_conv",
                "source_type": "experiment",
                "source_id": "gated_fno",
                "contribution_evidence": "Frequency processing.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is False
        assert any("NOT FOUND" in n for n in notes)

    def test_unknown_vocab_entry_skipped(self):
        """Component not in vocab seed → soft skip, still passes."""
        claims = [
            {
                "component": "custom_attention_layer",
                "source_type": "experiment",
                "source_id": "custom",
                "contribution_evidence": "Novel mechanism.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is True
        assert any("SKIPPED" in n for n in notes)

    def test_capability_without_pattern_skipped(self):
        """Capabilities have no pattern → soft skip."""
        claims = [
            {
                "component": "receptive_field",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Wide temporal coverage.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is True
        assert any("SKIPPED" in n for n in notes)

    def test_empty_claims_passes(self):
        """No inherited_components → check skipped entirely."""
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, [], SAMPLE_VOCAB)
        assert passed is True
        assert notes == []

    def test_mixed_pass_and_fail(self):
        """Some claims pass, one fails → overall fails."""
        claims = [
            {
                "component": "dilated_causal_conv",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Dilation.",
            },
            {
                "component": "spectral_conv",
                "source_type": "experiment",
                "source_id": "gated_fno",
                "contribution_evidence": "FFT.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is False
        assert len(notes) == 2
        # One found, one not
        found = [n for n in notes if "FOUND" in n and "NOT FOUND" not in n]
        not_found = [n for n in notes if "NOT FOUND" in n]
        assert len(found) == 1
        assert len(not_found) == 1

    def test_no_vocab_seed_all_skipped(self):
        """No vocab seed → all claims skipped (no patterns to check)."""
        claims = [
            {
                "component": "dilated_causal_conv",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Dilation.",
            },
        ]
        passed, notes = _check_inherited_components(WAVENET_LIKE_SOURCE, claims, None)
        assert passed is True
        assert all("SKIPPED" in n for n in notes)

    def test_case_insensitive_pattern(self):
        """Pattern matching is case-insensitive."""
        source = "self.embed = nn.embedding(256, 32)"  # lowercase
        claims = [
            {
                "component": "embedding_layer",
                "source_type": "experiment",
                "source_id": "punet",
                "contribution_evidence": "ADC encoding.",
            },
        ]
        passed, _notes = _check_inherited_components(source, claims, SAMPLE_VOCAB)
        assert passed is True

    def test_simple_source_fails_dilation_claim(self):
        """Simple CNN source has no dilation → claim fails."""
        claims = [
            {
                "component": "dilated_causal_conv",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Claimed but not used.",
            },
        ]
        passed, _notes = _check_inherited_components(SIMPLE_CNN_SOURCE, claims, SAMPLE_VOCAB)
        assert passed is False
