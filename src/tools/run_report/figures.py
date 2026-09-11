"""Matplotlib figures over the semantic projection. Generic only.

Every figure here draws one of §V.4's GENERIC rows and nothing else:
objective history · primary-metric trajectory · secondary trajectories ·
iteration status. Task-local presentation (waveform, image, video, spectrum)
is the example pack's, and there is no task name in this module.

Matplotlib is used headless (``Agg``) and is already a declared dependency
with zero other importers repo-wide (§V.12d), so the static report adds no
new dependency.

**No figure decides direction.** The direction words on every axis come from
the projection, which asked ``MetricOrder``. A ``Math.max``-shaped best-curve
would mark the WORST attempts as new bests under a minimised metric — the
defect F-12e-UX-3 names on the dashboard's side of the wire.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from execute_tools.run_report import RunReport, RunView

# Headless, unconditionally. This module runs from a CLI, from CI and from an
# example pack's README command, none of which has a display; `force=True` also
# overrides an MPLBACKEND a user happens to export. Set at import time rather
# than per call so a figure can never be built against an interactive backend.
matplotlib.use("Agg", force=True)

#: Figure size and resolution, chosen once so every panel matches.
_FIGSIZE = (9.0, 4.5)
_DPI = 130

#: The palette. Deliberately small and named by ROLE, not by task.
_C_PRIMARY = "#2b6cb0"
_C_BEST = "#dd6b20"
_C_TRAIN = "#2b6cb0"
_C_VALIDATION = "#805ad5"
_C_MUTED = "#a0aec0"


def _gapped(series: list[float | None]) -> list[float]:
    """A diverged epoch becomes an explicit NaN, so the curve BREAKS there.

    A ``None`` element is the storage image of a non-finite objective
    (``coerce_nonfinite_to_none`` writes JSON null for NaN/inf; ``#299`` made
    ``TrainingHistory`` and this report's projection declare the tolerant
    element type to match). matplotlib already coerces such an element to
    ``NaN`` internally and draws a gap — this makes that meaning EXPLICIT at
    the presentation boundary instead of leaning on an undocumented coercion
    inside a third-party stub, and it satisfies ``plot()``'s ``ArrayLike``
    parameter honestly rather than by silencing the checker.

    **Positions are preserved**, so ``epochs_completed == len(series)`` still
    holds through the figure. Filtering the ``None``s out instead would
    SHORTEN the curve — a run that diverged at epoch 3 of 5 would render as a
    healthy 4-point curve, which is the statistic-silently-wrong mode ``#299``
    exists to eliminate. The report shows the gap; it does not close over it.
    """
    return [float("nan") if v is None else v for v in series]


def _finish(fig: Figure, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=_DPI)
    plt.close(fig)
    return path.name


def plot_metric_trajectory(report: RunReport, out_dir: Path) -> str | None:
    """The primary-metric trajectory with its direction-aware best-so-far.

    Returns ``None`` — drawing NOTHING — when the projection refused to
    establish a metric identity. A trajectory chart with no declared direction
    is exactly the confident-and-wrong artifact §V.4 rule 2 forbids, and an
    absent chart beside the report's named refusal is the honest alternative.
    """
    trajectory = report.trajectory
    if trajectory.metric is None or not trajectory.points:
        return None

    xs = list(range(1, len(trajectory.points) + 1))
    scores = [p.score for p in trajectory.points]
    best = [p.best_so_far for p in trajectory.points]

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(xs, best, color=_C_BEST, lw=2.0, label="cumulative best", zorder=2)
    ax.plot(
        xs,
        scores,
        color=_C_PRIMARY,
        lw=1.3,
        ls="--",
        marker="o",
        ms=4,
        label="attempt score",
        zorder=3,
    )
    new_best_x = [x for x, p in zip(xs, trajectory.points, strict=True) if p.is_new_best]
    new_best_y = [p.best_so_far for p in trajectory.points if p.is_new_best]
    if new_best_x:
        ax.scatter(
            new_best_x,
            new_best_y,
            marker="*",
            s=160,
            color=_C_BEST,
            edgecolors="white",
            linewidths=0.6,
            zorder=4,
            label="new best",
        )

    ax.set_xlabel("scored attempt (in chain order)")
    # The caption states the direction the projection resolved. It is not a
    # constant: under a `lower` metric this reads "lower is better", and the
    # best-curve above descends, because both come from the same MetricOrder.
    ax.set_ylabel(trajectory.metric.label)
    ax.set_title(f"Primary metric — {trajectory.metric.verb} `{trajectory.metric.metric_id}`")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9)
    return _finish(fig, out_dir / "primary_metric_trajectory.png")


def plot_objective_history(run: RunView, out_dir: Path, *, index: int) -> str | None:
    """Per-epoch training and validation objective for one run.

    The series are labelled with the framework's typed ``objective_kind`` —
    NOT "loss" (§V.4 rule 1). When the R2/R3 ``comparability`` stamp is
    ``not_established`` the caption says so and names the reason: drawing both
    curves on one axis without that note would imply a comparison the
    framework explicitly refused to certify.
    """
    series = [(a, a.objective) for a in run.attempts if a.objective is not None]
    series = [(a, o) for a, o in series if o is not None and o.train_objective]
    if not series:
        return None

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    kinds: set[str] = set()
    notes: list[str] = []
    for attempt, objective in series:
        assert objective is not None  # filtered above
        kinds.add(objective.objective_kind)
        epochs = list(range(1, objective.epochs_completed + 1))
        ax.plot(
            epochs,
            _gapped(objective.train_objective),
            color=_C_TRAIN,
            lw=1.6,
            marker="o",
            ms=3.5,
            label=f"{attempt.exp_id} · train",
        )
        if objective.validation_objective is not None:
            ax.plot(
                epochs,
                _gapped(objective.validation_objective),
                color=_C_VALIDATION,
                lw=1.6,
                ls="--",
                marker="s",
                ms=3.5,
                label=f"{attempt.exp_id} · validation",
            )
        else:
            notes.append(f"{attempt.exp_id}: no validation pass recorded")
        if objective.comparability != "established":
            notes.append(
                f"{attempt.exp_id}: train/validation not comparable "
                f"({objective.comparability_reason})"
            )
        if objective.truncated:
            notes.append(
                f"{attempt.exp_id}: truncated at "
                f"{objective.epochs_completed}/{objective.epochs_planned} epochs"
            )

    kind_label = ", ".join(sorted(kinds))
    ax.set_xlabel("epoch")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel(f"training objective ({kind_label})")
    ax.set_title(f"Training objective — {run.run_name} · {run.model_type}")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    if notes:
        ax.text(
            0.01,
            -0.22,
            " · ".join(dict.fromkeys(notes)),
            transform=ax.transAxes,
            fontsize=7.5,
            color=_C_MUTED,
            va="top",
        )
    return _finish(fig, out_dir / f"objective_history_{index:03d}.png")


def plot_secondary_metrics(report: RunReport, out_dir: Path) -> str | None:
    """One panel per DECLARED secondary metric, each with its OWN direction.

    Secondaries are OBSERVATIONAL (Q-09-7 = B): they are plotted, never ranked
    and never compared to the primary. Each panel asks its own metric's
    direction — DAVIS declares a ``higher`` ``psnr`` beside a ``lower`` ``mse``
    primary, and inheriting the run's direction would label it backwards.

    Declared-but-not-evaluated points are ABSENT from the line and counted in
    the caption as a NAMED absence, never plotted as zero.
    """
    declared: list[str] = []
    for run in report.runs:
        for metric in run.secondary_metrics:
            if metric.metric_id not in declared:
                declared.append(metric.metric_id)
    if not declared:
        return None

    fig, axes = plt.subplots(
        len(declared), 1, figsize=(_FIGSIZE[0], 2.4 * len(declared) + 1.0), squeeze=False
    )
    for row, metric_id in enumerate(declared):
        ax = axes[row][0]
        xs: list[int] = []
        ys: list[float] = []
        label = metric_id
        absent = 0
        position = 0
        for run in report.runs:
            for attempt in run.attempts:
                for secondary in attempt.secondaries:
                    if secondary.metric.metric_id != metric_id:
                        continue
                    position += 1
                    label = secondary.metric.label
                    if secondary.status == "scored" and secondary.scalar is not None:
                        xs.append(position)
                        ys.append(secondary.scalar)
                    else:
                        absent += 1
        if xs:
            ax.plot(xs, ys, color=_C_PRIMARY, lw=1.5, marker="o", ms=4)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(True, alpha=0.25)
        caption = "observational — never ranked against the primary"
        if absent:
            caption += f" · {absent} attempt(s) declared it but recorded no value"
        if not xs:
            # A declared secondary that this corpus never evaluated still gets
            # its panel. "Declared and never evaluated" is a fact worth
            # showing, and it is precisely the silence the three-state
            # scored/refused/unavailable vocabulary exists to break.
            caption = f"declared, no value recorded in this corpus · {caption}"
        ax.set_title(caption, fontsize=8, color=_C_MUTED, loc="left")
    axes[-1][0].set_xlabel("attempt (in chain order)")
    axes[-1][0].xaxis.set_major_locator(MaxNLocator(integer=True))
    return _finish(fig, out_dir / "secondary_metrics.png")


def plot_status_breakdown(report: RunReport, out_dir: Path) -> str | None:
    """Attempt outcomes by the framework's OWN 13-status vocabulary.

    The statuses are not collapsed into "ok / not ok". Each one says something
    different about what happened — ``skipped_resource_admission`` says nothing
    about the candidate, ``failed_mode_collapse`` says everything — and the
    dashboard's charts filter every non-success away entirely (§V.12a).
    """
    counts: dict[str, int] = {}
    for run in report.runs:
        for status, count in run.status_counts.items():
            counts[status] = counts.get(status, 0) + count
    if not counts:
        return None

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    labels = [k for k, _ in ordered]
    values = [v for _, v in ordered]
    fig, ax = plt.subplots(figsize=(_FIGSIZE[0], max(2.4, 0.42 * len(labels) + 1.4)))
    ax.barh(labels, values, color=_C_PRIMARY)
    ax.invert_yaxis()
    ax.set_xlabel("attempts")
    ax.set_title("Attempt outcomes, by the framework's own status vocabulary")
    ax.grid(True, axis="x", alpha=0.25)
    for y, value in enumerate(values):
        ax.text(value, y, f" {value}", va="center", fontsize=9)
    return _finish(fig, out_dir / "status_breakdown.png")


def render_figures(report: RunReport, out_dir: Path) -> dict[str, list[str]]:
    """Draw every generic figure the corpus supports.

    Returns a mapping of figure ROLE to the filenames written. A role whose
    data is absent yields an empty list — the HTML then states the absence by
    name rather than embedding a broken image.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    trajectory = plot_metric_trajectory(report, out_dir)
    secondary = plot_secondary_metrics(report, out_dir)
    status = plot_status_breakdown(report, out_dir)
    objectives = [
        name
        for name in (
            plot_objective_history(run, out_dir, index=index)
            for index, run in enumerate(report.runs)
        )
        if name is not None
    ]
    return {
        "primary_metric_trajectory": [trajectory] if trajectory else [],
        "objective_history": objectives,
        "secondary_metrics": [secondary] if secondary else [],
        "status_breakdown": [status] if status else [],
    }
