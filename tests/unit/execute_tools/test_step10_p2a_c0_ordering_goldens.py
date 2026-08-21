"""Step 10 / P2a — C0: pre-migration ordering goldens for sites 1-5.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §6 (the three-task fixtures), §7's
binding ordering-evidence rule, C0 step 6.

Why a SEQUENCE and not a winner
-------------------------------
The claim P2a must eventually make is *"TIDMAD behaviour is unchanged"*. That
claim is worth nothing if it is checked on the final winner alone: a comparator
with the direction inverted still picks the right winner on any fixture whose
best element happens to come first, and on a three-element fixture it has a
one-in-three chance of doing so by accident. So every golden here records the
ORDERED LIST OF PAIRWISE DECISIONS a fixture drives — the incumbent after each
step, and for the pure predicates the boolean each comparison returned.

Where the expectations come from
--------------------------------
Every expected value in this module is a **hand-computed literal**, written
from the metric's declared direction and the site's documented tie rules — never
produced by running the code under test and pasting the result. For the two
sites that are directly callable pure functions (4 and 5) the current
production implementation is then executed against those literals, which is
what makes this a genuine PRE-MIGRATION baseline rather than a restatement of
the same arithmetic: if the transcription were wrong, the capture would
disagree with it here, at the base, before anything moved.

Sites 1-3 are inline folds inside ``run_model_exploration``'s loop and are not
callable in isolation at the base. Their goldens are therefore the hand-computed
INCUMBENT TRAJECTORIES the fixtures must drive, plus the counterfactual
trajectory a direction-blind fold produces on the same DAVIS input. C1 asserts
the migrated code reproduces the former and not the latter; the census in
``test_step10_p2a_c0_ordering_scanner.py`` independently pins that the
predicates are still the raw ones at this commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.resume import _pick_best
from execute_tools.metric_order import MetricOrder
from execute_tools.per_file_best import _row_beats, _RowCandidate
from tests.helpers.metric_fixtures import shipped_spec

#: TIDMAD's shipped `higher` order. C2 made the order an explicit argument;
#: passing the SHIPPED spec is what makes these calls reproduce the frozen
#: pre-migration numbers rather than merely agree with themselves.
_TIDMAD_ORDER = MetricOrder(shipped_spec())

GOLDEN_PATH = Path(__file__).resolve().parent / "goldens" / "step10_p2a_c0_ordering_sequences.json"

# ---------------------------------------------------------------------------
# §6 three-task fixtures — the declared literals
# ---------------------------------------------------------------------------

#: TIDMAD: higher-is-better with NEGATIVE values. -1.4 beats -3.2 beats -7.9.
#: The negative sign is the point: a comparator that reads "bigger magnitude is
#: better" inverts here while looking correct on any positive fixture.
TIDMAD_SCORES: tuple[float, ...] = (-3.2, -1.4, -7.9)

#: Pets: 37-way classification accuracy, higher-is-better on [0, 1].
#: 0.027 is the real D14 constant-prediction collapse (chance = 1/37).
PETS_SCORES: tuple[float, ...] = (0.027, 0.61, 0.33)

#: DAVIS: global MSE, LOWER-is-better. The values sit close together on purpose
#: — this is the fixture on which a direction-blind fold selects the worst.
DAVIS_SCORES: tuple[float, ...] = (0.0174, 0.0172, 0.0210)


# ---------------------------------------------------------------------------
# Sites 1-3 — hand-computed incumbent trajectories
# ---------------------------------------------------------------------------

#: Site 1/2's fold: ``incumbent is None or candidate BETTER-THAN incumbent``.
#: Strictly better, so a tie keeps the earliest holder (design §2.1 note).
#:
#: TIDMAD (higher, negative values), hand-computed:
#:   -3.2 : no incumbent          -> ADVANCE, incumbent -3.2
#:   -1.4 : -1.4 > -3.2  (better) -> ADVANCE, incumbent -1.4
#:   -7.9 : -7.9 > -1.4  (worse)  -> HOLD,    incumbent -1.4
TIDMAD_INCUMBENT_DECISIONS: tuple[bool, ...] = (True, True, False)
TIDMAD_INCUMBENT_TRAJECTORY: tuple[float, ...] = (-3.2, -1.4, -1.4)

#: Pets (higher, [0,1]), hand-computed:
#:   0.027 : no incumbent            -> ADVANCE, incumbent 0.027
#:   0.61  : 0.61 > 0.027  (better)  -> ADVANCE, incumbent 0.61
#:   0.33  : 0.33 > 0.61   (worse)   -> HOLD,    incumbent 0.61
PETS_INCUMBENT_DECISIONS: tuple[bool, ...] = (True, True, False)
PETS_INCUMBENT_TRAJECTORY: tuple[float, ...] = (0.027, 0.61, 0.61)

#: DAVIS (LOWER), hand-computed under the CORRECT direction:
#:   0.0174 : no incumbent               -> ADVANCE, incumbent 0.0174
#:   0.0172 : 0.0172 < 0.0174 (better)   -> ADVANCE, incumbent 0.0172
#:   0.0210 : 0.0210 < 0.0172 (worse)    -> HOLD,    incumbent 0.0172
DAVIS_INCUMBENT_DECISIONS: tuple[bool, ...] = (True, True, False)
DAVIS_INCUMBENT_TRAJECTORY: tuple[float, ...] = (0.0174, 0.0172, 0.0172)

#: The SAME DAVIS input through the direction-BLIND fold that is live at this
#: commit (a raw ``>``), hand-computed:
#:   0.0174 : no incumbent           -> ADVANCE, incumbent 0.0174
#:   0.0172 : 0.0172 > 0.0174 = False -> HOLD,   incumbent 0.0174   <-- the defect
#:   0.0210 : 0.0210 > 0.0174 = True  -> ADVANCE, incumbent 0.0210  <-- the WORST
#:
#: This is the counterfactual C1 must move away from. Recording it here, at the
#: base, is what lets C1 prove it CHANGED something rather than merely that it
#: still passes.
DAVIS_DIRECTION_BLIND_DECISIONS: tuple[bool, ...] = (True, False, True)
DAVIS_DIRECTION_BLIND_TRAJECTORY: tuple[float, ...] = (0.0174, 0.0174, 0.0210)

#: Site 3's early stop: ``best_score_overall AT-LEAST target``.
#: DAVIS target 0.0173 under LOWER: 0.0172 <= 0.0173 satisfies; 0.0174 does not.
#: Under the direction-blind ``>=`` live at this commit the verdicts invert.
DAVIS_TARGET: float = 0.0173
DAVIS_TARGET_SATISFIED_CORRECT: tuple[bool, ...] = (False, True, False)
DAVIS_TARGET_SATISFIED_DIRECTION_BLIND: tuple[bool, ...] = (True, False, True)


class TestSiteOneToThreeTrajectoryGoldens:
    """The hand-computed trajectories, and the internal consistency of the set."""

    def test_the_tidmad_trajectory_is_self_consistent(self):
        """A decision list and a trajectory must describe the SAME fold.

        Cheap, but it is the check that catches a transcription slip in the
        literals above — which would otherwise become a golden that C1 happily
        reproduces while both are wrong.
        """
        assert _fold(TIDMAD_SCORES, TIDMAD_INCUMBENT_DECISIONS) == TIDMAD_INCUMBENT_TRAJECTORY

    def test_the_pets_trajectory_is_self_consistent(self):
        assert _fold(PETS_SCORES, PETS_INCUMBENT_DECISIONS) == PETS_INCUMBENT_TRAJECTORY

    def test_the_davis_trajectory_is_self_consistent(self):
        assert _fold(DAVIS_SCORES, DAVIS_INCUMBENT_DECISIONS) == DAVIS_INCUMBENT_TRAJECTORY

    def test_the_davis_direction_blind_trajectory_is_self_consistent(self):
        assert (
            _fold(DAVIS_SCORES, DAVIS_DIRECTION_BLIND_DECISIONS) == DAVIS_DIRECTION_BLIND_TRAJECTORY
        )

    def test_the_davis_fixture_actually_discriminates_direction(self):
        """Anti-vacuity: the DAVIS golden is only evidence if the two folds DIFFER.

        A fixture on which the correct and the direction-blind fold agree
        proves nothing about direction, and would let C1 pass with the defect
        intact.
        """
        assert DAVIS_INCUMBENT_TRAJECTORY != DAVIS_DIRECTION_BLIND_TRAJECTORY
        assert DAVIS_INCUMBENT_TRAJECTORY[-1] == min(DAVIS_SCORES)
        assert DAVIS_DIRECTION_BLIND_TRAJECTORY[-1] == max(DAVIS_SCORES)

    def test_the_tidmad_fixture_exercises_the_negative_regime(self):
        """The TIDMAD golden must keep its distinguishing property.

        Every score negative, and the best one NOT the first element — so a
        fold that simply keeps its first input also fails.
        """
        assert all(score < 0 for score in TIDMAD_SCORES)
        assert TIDMAD_INCUMBENT_TRAJECTORY[-1] == max(TIDMAD_SCORES)
        assert TIDMAD_INCUMBENT_TRAJECTORY[-1] != TIDMAD_SCORES[0]

    def test_the_davis_target_verdicts_invert_between_the_two_folds(self):
        assert DAVIS_TARGET_SATISFIED_CORRECT != DAVIS_TARGET_SATISFIED_DIRECTION_BLIND
        # hand-check the one that matters: 0.0172 clears a 0.0173 target when
        # lower is better, and 0.0174 does not.
        assert DAVIS_TARGET_SATISFIED_CORRECT[DAVIS_SCORES.index(0.0172)] is True
        assert DAVIS_TARGET_SATISFIED_CORRECT[DAVIS_SCORES.index(0.0174)] is False


def _fold(scores: tuple[float, ...], decisions: tuple[bool, ...]) -> tuple[float, ...]:
    """Replay a decision list into the incumbent trajectory it implies."""
    incumbent: float | None = None
    out: list[float] = []
    for score, advanced in zip(scores, decisions, strict=True):
        if advanced:
            incumbent = score
        assert incumbent is not None
        out.append(incumbent)
    return tuple(out)


# ---------------------------------------------------------------------------
# Site 4 — core.resume._pick_best, captured from the live implementation
# ---------------------------------------------------------------------------


def _record(exp_id: str, score: float) -> dict[str, Any]:
    return {"exp_id": exp_id, "denoising_score": score}


#: TIDMAD pool, hand-computed expectation. ``_pick_best`` takes the best score;
#: on a tie it takes the lexicographically smallest ``exp_id``.
#:
#:   prefix [a:-3.2]                  -> best a  (only candidate)
#:   prefix [a:-3.2, b:-1.4]          -> best b  (-1.4 > -3.2)
#:   prefix [a:-3.2, b:-1.4, c:-7.9]  -> best b  (-7.9 loses)
TIDMAD_PICK_BEST_POOL = (
    _record("exp_a", -3.2),
    _record("exp_b", -1.4),
    _record("exp_c", -7.9),
)
TIDMAD_PICK_BEST_TRAJECTORY: tuple[str, ...] = ("exp_a", "exp_b", "exp_b")

#: The tie fixture. Equal scores, so the tie rule alone decides, and it must be
#: DIRECTION-INDEPENDENT: lexicographic smallest ``exp_id`` wins whether the
#: metric is maximised or minimised. P2a migrates the score comparison only —
#: this trajectory must survive byte-identical.
TIE_PICK_BEST_POOL = (
    _record("exp_m", -2.0),
    _record("exp_b", -2.0),
    _record("exp_z", -2.0),
)
TIE_PICK_BEST_TRAJECTORY: tuple[str, ...] = ("exp_m", "exp_b", "exp_b")


class TestSiteFourPickBestGolden:
    """The running incumbent over growing prefixes, read from PRODUCTION.

    Calling ``_pick_best`` on prefixes 1..n reads the incumbent trajectory out
    of the production function rather than out of a replica of it.

    C2 note — how this stayed a PRE-migration baseline after the migration.
    The expectations above were hand-computed and the manifest beside this
    module was captured and COMMITTED at the base commit, before any
    production comparison moved. C2 then gave ``_pick_best`` a keyword-only
    ``MetricOrder``, so the calls below now pass TIDMAD's ``higher`` order —
    and must reproduce the frozen numbers exactly. That is the parity claim,
    not a restatement of it: the evidence predates the change and lives in
    version control, while the code being measured is the current one.
    """

    def test_the_tidmad_pick_best_trajectory_matches_the_hand_computed_golden(self):
        assert _pick_best_trajectory(TIDMAD_PICK_BEST_POOL) == TIDMAD_PICK_BEST_TRAJECTORY

    def test_the_tie_trajectory_is_lexicographic_and_direction_independent(self):
        assert _pick_best_trajectory(TIE_PICK_BEST_POOL) == TIE_PICK_BEST_TRAJECTORY

    def test_the_tie_fixture_really_is_a_tie(self):
        """Anti-vacuity: if the scores differed, the tie rule would be untested."""
        scores = {r["denoising_score"] for r in TIE_PICK_BEST_POOL}
        assert len(scores) == 1

    def test_the_tie_winner_is_not_merely_the_first_element(self):
        """``exp_b`` arrives SECOND, so 'keep the first' also fails this."""
        assert TIE_PICK_BEST_TRAJECTORY[-1] == "exp_b"
        assert TIE_PICK_BEST_POOL[0]["exp_id"] == "exp_m"


def _pick_best_trajectory(pool: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    out: list[str] = []
    for size in range(1, len(pool) + 1):
        best = _pick_best([dict(r) for r in pool[:size]], order=_TIDMAD_ORDER)
        assert best is not None
        out.append(str(best["exp_id"]))
    return tuple(out)


# ---------------------------------------------------------------------------
# Site 5 — execute_tools.per_file_best._row_beats, captured pairwise
# ---------------------------------------------------------------------------


def _row(
    *,
    best_linear: float,
    iter_idx: int = 1,
    round_index: int | None = 1,
    round_provenance: str = "persisted",
    exp_id: str = "exp_a",
) -> _RowCandidate:
    return _RowCandidate(
        file_index=6,
        phase="formal",
        validity_row="valid",
        best_linear=best_linear,
        iter_idx=iter_idx,
        round_index=round_index,
        round_provenance=round_provenance,
        exp_id=exp_id,
        model_type="wavenet",
        model_params=1000,
        eval_strategy="snapshot",
        eval_portion=0.1,
        gate_summary={},
        timestamp="2026-08-20T00:00:00Z",
    )


#: Pairwise probes for ``_row_beats(new, current)``, with the hand-computed
#: verdict for each. Every tie class from the function's documented rule chain
#: is represented, so a regression names WHICH rule broke.
#:
#: ``best_linear`` values are TIDMAD per-file linear-space values (positive,
#: higher-is-better) — the space the persisted ``file_vector`` entries live in.
ROW_BEATS_PROBES: tuple[tuple[str, _RowCandidate, _RowCandidate, bool], ...] = (
    (
        "higher linear score wins",
        _row(best_linear=9.0),
        _row(best_linear=4.0),
        True,
    ),
    (
        "lower linear score loses",
        _row(best_linear=4.0),
        _row(best_linear=9.0),
        False,
    ),
    (
        "tie on score -> earlier iteration wins",
        _row(best_linear=5.0, iter_idx=2),
        _row(best_linear=5.0, iter_idx=7),
        True,
    ),
    (
        "tie on score -> later iteration loses",
        _row(best_linear=5.0, iter_idx=7),
        _row(best_linear=5.0, iter_idx=2),
        False,
    ),
    (
        "tie on score and iteration -> persisted beats legacy-unknown",
        _row(best_linear=5.0, round_provenance="persisted"),
        _row(best_linear=5.0, round_provenance="unknown"),
        True,
    ),
    (
        "tie on score and iteration -> legacy-unknown loses to persisted",
        _row(best_linear=5.0, round_provenance="unknown"),
        _row(best_linear=5.0, round_provenance="persisted"),
        False,
    ),
    (
        "tie through provenance -> smaller round_index wins",
        _row(best_linear=5.0, round_index=2),
        _row(best_linear=5.0, round_index=8),
        True,
    ),
    (
        "tie through round_index -> lexicographic exp_id wins",
        _row(best_linear=5.0, exp_id="exp_b"),
        _row(best_linear=5.0, exp_id="exp_m"),
        True,
    ),
    (
        "tie through round_index -> lexicographically larger exp_id loses",
        _row(best_linear=5.0, exp_id="exp_m"),
        _row(best_linear=5.0, exp_id="exp_b"),
        False,
    ),
)


class TestSiteFiveRowBeatsGolden:
    """Real pre-migration capture of the pairwise predicate, tie class by tie class."""

    def test_every_probe_matches_its_hand_computed_verdict(self):
        actual = [_row_beats(new, cur, order=_TIDMAD_ORDER) for _, new, cur, _ in ROW_BEATS_PROBES]
        expected = [verdict for _, _, _, verdict in ROW_BEATS_PROBES]
        mismatches = [
            name
            for (name, _, _, want), got in zip(ROW_BEATS_PROBES, actual, strict=True)
            if want is not got
        ]
        assert not mismatches, f"pre-migration _row_beats disagrees with the golden: {mismatches}"
        assert actual == expected

    def test_the_probe_set_covers_every_tie_rule(self):
        """A golden that skips a tie class cannot notice that class breaking."""
        names = " ".join(name for name, _, _, _ in ROW_BEATS_PROBES)
        for rule in ("iteration", "persisted", "round_index", "exp_id"):
            assert rule in names, f"no probe exercises the {rule!r} tie rule"

    def test_the_score_probes_are_the_only_direction_sensitive_ones(self):
        """Exactly two probes turn on the SCORE; the other seven are tie rules.

        This is the split C2 must preserve: migrating the score comparison may
        change the first two under a ``lower`` metric and must leave the other
        seven untouched under BOTH.
        """
        score_probes = [
            name for name, new, cur, _ in ROW_BEATS_PROBES if new.best_linear != cur.best_linear
        ]
        assert len(score_probes) == 2
        assert len(ROW_BEATS_PROBES) - len(score_probes) == 7


# ---------------------------------------------------------------------------
# The frozen manifest
# ---------------------------------------------------------------------------


class TestTheFrozenGoldenManifest:
    """The captured sequences, frozen on disk at the P2a implementation base.

    Committed so a later commit compares against evidence recorded BEFORE the
    migration, not against whatever the code does at the time the comparison
    runs.
    """

    def test_the_manifest_matches_the_live_pre_migration_capture(self):
        assert GOLDEN_PATH.exists(), (
            f"the frozen C0 golden is missing: {GOLDEN_PATH}. It is committed "
            "evidence, not a cache — regenerate it only at the base commit."
        )
        frozen = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        assert frozen["sites"]["site_4_pick_best"]["tidmad_trajectory"] == list(
            _pick_best_trajectory(TIDMAD_PICK_BEST_POOL)
        )
        assert frozen["sites"]["site_4_pick_best"]["tie_trajectory"] == list(
            _pick_best_trajectory(TIE_PICK_BEST_POOL)
        )
        assert frozen["sites"]["site_5_row_beats"]["verdicts"] == [
            _row_beats(new, cur, order=_TIDMAD_ORDER) for _, new, cur, _ in ROW_BEATS_PROBES
        ]

    def test_the_manifest_records_the_trajectories_sites_one_to_three_must_drive(self):
        frozen = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        folds = frozen["sites"]["sites_1_3_incumbent_fold"]
        assert folds["tidmad"]["trajectory"] == list(TIDMAD_INCUMBENT_TRAJECTORY)
        assert folds["pets"]["trajectory"] == list(PETS_INCUMBENT_TRAJECTORY)
        assert folds["davis"]["trajectory"] == list(DAVIS_INCUMBENT_TRAJECTORY)
        assert folds["davis_direction_blind"]["trajectory"] == list(
            DAVIS_DIRECTION_BLIND_TRAJECTORY
        )
