"""Method-name-free paraphrase audit for reference SkillCards."""

from __future__ import annotations

import json
from pathlib import Path

from agent.data_analysis.discovery import discover_skills, search_skill_cards
from agent.data_analysis.reference_packs import builtin_pack_refs

PARAPHRASES: dict[str, tuple[str, ...]] = {
    "summary_statistics": (
        "What are the central tendency and spread of these measurements?",
        "Give a compact numerical overview of the observed values.",
        "How large and variable are the measurements?",
    ),
    "nonfinite_and_missingness": (
        "Are observations absent, NaN, or infinite?",
        "Check the data for unusable or unavailable values.",
        "How much of the dataset is incomplete or non-finite?",
    ),
    "distribution_quantiles_and_outliers": (
        "Are there unusually extreme observations in the tails?",
        "Describe the shape and percentiles of the value distribution.",
        "How many measurements lie beyond robust fences?",
    ),
    "correlation_matrix": (
        "Which numeric variables move together linearly?",
        "Check pairwise association among the measured variables.",
        "Are any columns strongly related to each other?",
    ),
    "performance_slice_summary": (
        "Does model error become worse as metadata variable x increases?",
        "Which authorized subgroups have the largest prediction error?",
        "Compare bias and accuracy across categories of an auxiliary variable.",
    ),
    "prediction_target_distribution": (
        "Are predictions compressed toward the mean relative to truth?",
        "Check whether predicted values have the same range and variance as targets.",
        "Is the regressor biased or collapsing its output distribution?",
    ),
    "sampling_cadence_and_gaps": (
        "Are observations evenly spaced and are there gaps?",
        "How consistent is the interval between measurements?",
        "What usable duration remains after missing observations?",
    ),
    "temporal_stability_summary": (
        "Does the signal mean or variance drift through the observation?",
        "Are local statistics stable from the beginning to the end?",
        "Does amplitude change across temporal windows?",
    ),
    "autocorrelation": (
        "Does the sequence repeat after a characteristic delay?",
        "How much memory remains across different lags?",
        "Is there recurring structure in the signal over time?",
    ),
    "fft_peak_summary": (
        "Which discrete frequencies have the largest amplitudes?",
        "Find sharp periodic components in a regularly sampled signal.",
        "Is energy concentrated at a few frequency peaks?",
    ),
    "welch_psd": (
        "What does the broadband noise floor look like across frequency?",
        "Estimate how signal power density is distributed over frequency.",
        "Is there a robust narrowband peak above background noise?",
    ),
    "band_power_summary": (
        "How much power lies inside each supplied physical frequency interval?",
        "Compare energy between low and high frequency ranges.",
        "Which caller-defined spectral band contains more signal energy?",
    ),
    "stft_energy_map": (
        "Does the dominant frequency change over time?",
        "Is there transient spectral structure during the sequence?",
        "Does the signal sweep through frequency?",
    ),
    "lomb_scargle_periodogram": (
        "The observations are unevenly spaced; is there a periodic component?",
        "Search for periodicity despite timestamp jitter and gaps.",
        "Which periods are supported by irregular samples?",
    ),
    "cross_correlation": (
        "Does the second sensor follow the first after a delay?",
        "At what time offset are two channels most strongly related?",
        "Measure the lag between an ordered pair of signals.",
    ),
    "magnitude_squared_coherence": (
        "Do these two channels share oscillatory structure?",
        "At which frequencies are two sensors linearly related?",
        "Is their common variation localized to particular frequencies?",
    ),
    "residual_spectrum": (
        "Does model error retain frequency-dependent structure?",
        "Are prediction residuals spectrally white or structured?",
        "Which frequencies still contain unexplained error power?",
    ),
}


def discoverability_audit(*, limit: int = 8) -> tuple[dict[str, object], ...]:
    snapshot = discover_skills(builtin_pack_refs("core-analysis", "time-series"))
    rows = []
    for skill_id, questions in PARAPHRASES.items():
        for question in questions:
            candidates = search_skill_cards(snapshot, question, limit=limit)
            candidate_ids = [item.card.skill_id for item in candidates]
            rows.append(
                {
                    "skill_id": skill_id,
                    "question": question,
                    "candidate_skill_ids": candidate_ids,
                    "rank": (
                        candidate_ids.index(skill_id) + 1 if skill_id in candidate_ids else None
                    ),
                    "recalled": skill_id in candidate_ids,
                }
            )
    return tuple(rows)


def write_discoverability_receipt(output_directory: Path, *, limit: int = 8) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    rows = discoverability_audit(limit=limit)
    (output_directory / "discoverability.json").write_text(
        json.dumps(rows, sort_keys=True, indent=2) + "\n"
    )
    grouped = {
        skill_id: [row for row in rows if row["skill_id"] == skill_id] for skill_id in PARAPHRASES
    }
    lines = [
        "# Reference-skill paraphrase discoverability",
        "",
        f"Manifest-only retrieval, recall@{limit}; methods are not named in questions.",
        "",
        "| Skill | Recalled | Worst rank | Questions |",
        "|---|---:|---:|---:|",
    ]
    for skill_id, skill_rows in grouped.items():
        ranks = [row["rank"] for row in skill_rows if row["rank"] is not None]
        lines.append(
            f"| `{skill_id}` | {sum(bool(row['recalled']) for row in skill_rows)}/"
            f"{len(skill_rows)} | {max(ranks) if ranks else 'MISS'} | {len(skill_rows)} |"
        )
    recalled = sum(bool(row["recalled"]) for row in rows)
    lines.extend(
        [
            "",
            f"Overall recall@{limit}: **{recalled}/{len(rows)} ({recalled / len(rows):.1%})**.",
            "",
            "The receipt measures planner visibility, not final selection quality.",
        ]
    )
    path = output_directory / "discoverability.md"
    path.write_text("\n".join(lines) + "\n")
    return path
