"""A drawing that stops being worked has to be able to end.

Cap-length `geometric` pieces stop marking entirely after ~1h and then sit
untouched for ~7h until the 8-hour cap. The cause is a closed loop rather than
a mistuned number:

    _update_attention runs once per PLACED MARK
      -> fatigue, curiosity, engagement only advance when a mark lands
      -> rising fatigue lowers derived_energy
      -> `draw_chance *= energy`, which has no floor
      -> marks become rare, then stop
      -> the state that could end the piece stops moving with them

So fatigue can never climb to the 0.90 `bailout_fatigue`, energy can never fall
to the 0.05 `bailout_stalled`, and `earned_settled` correctly refuses because an
idle sample HOLDS its streak. Every exit is driven by a quantity that only
advances when marks happen.

These tests pin the deadlock, the detector that reads around it, and the first
real consumer of `occupied_cells()`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anima_mcp.display.drawing_engine import (  # noqa: E402
    FROZEN_FRAC_OF_PEAK,
    FROZEN_STREAK_SAMPLES,
    MIN_RECORDED_DRAWING_PIXELS,
    SETTLED_MIN_AGE_SECONDS,
    SETTLED_MIN_MARKS,
    DrawingState,
    _EARNED_COMPLETION_REASONS,
    is_earned_completion_reason,
)


class _Canvas:
    """Minimal canvas stand-in carrying only what the predicates read."""

    def __init__(self, *, pixels=5000, marks=70, age=3 * 3600,
                 idle_streak=FROZEN_STREAK_SAMPLES, mark_peak=8.0):
        self.pixels = {i: 1 for i in range(pixels)}
        self.mark_count = marks
        self.last_clear_time = time.time() - age
        self.drawing_start_time = self.last_clear_time
        self._novelty_settling = {
            "last_t": time.time(), "last_px": pixels, "last_marks": marks,
            "recent": [], "peak": 0.0, "streak": 0,
            "mark_peak": mark_peak, "idle_streak": idle_streak,
            "last_cells": 12,
        }

    def compositional_satisfaction(self):
        return 0.0


def _frozen_state():
    """Attention state as it sits in a frozen piece: high but under the bail."""
    st = DrawingState()
    st.reset()
    st.fatigue = 0.85       # under the 0.90 bailout_fatigue
    st.curiosity = 0.30
    st.engagement = 0.20
    st.arc_phase = "developing"
    return st


class TestTheDeadlock:

    def test_frozen_attention_reaches_no_existing_bailout(self):
        """The trap: every other exit needs state that has stopped advancing."""
        st = _frozen_state()
        assert st.fatigue < 0.90, "would have fired bailout_fatigue"
        assert st.derived_energy >= 0.05, "would have fired bailout_stalled"
        assert not st.attention_exhausted()
        assert not st.coherence_settled()

    def test_attention_only_advances_on_a_placed_mark(self):
        """Why the deadlock closes: no wall-clock term anywhere in fatigue."""
        st = _frozen_state()
        before = (st.fatigue, st.curiosity, st.engagement)
        time.sleep(0)  # time passing is not an input
        assert (st.fatigue, st.curiosity, st.engagement) == before


class TestFrozenDetection:

    def test_fires_when_marks_have_stopped(self):
        st = _frozen_state()
        assert st.completion_reason(_Canvas()) == "bailout_frozen"

    def test_needs_a_full_idle_streak(self):
        st = _frozen_state()
        canvas = _Canvas(idle_streak=FROZEN_STREAK_SAMPLES - 1)
        assert st.completion_reason(canvas) != "bailout_frozen"

    def test_a_piece_that_never_marked_is_not_frozen(self):
        """No established rate means nothing to be idle against."""
        st = _frozen_state()
        assert st.completion_reason(_Canvas(mark_peak=0.0)) != "bailout_frozen"

    def test_young_piece_is_not_frozen(self):
        st = _frozen_state()
        canvas = _Canvas(age=SETTLED_MIN_AGE_SECONDS - 60)
        assert st.completion_reason(canvas) != "bailout_frozen"

    def test_thin_piece_is_not_frozen(self):
        st = _frozen_state()
        canvas = _Canvas(pixels=MIN_RECORDED_DRAWING_PIXELS - 1)
        assert st.completion_reason(canvas) != "bailout_frozen"

    def test_corrupt_tracker_does_not_raise(self):
        st = _frozen_state()
        canvas = _Canvas()
        for junk in ("nonsense", None, {"idle_streak": "many"}, {}):
            canvas._novelty_settling = junk
            assert st.marks_stopped(canvas) is False

    def test_no_mark_count_floor(self):
        """⛔ The trap this gate must not fall into.

        SETTLED_MIN_MARKS is 100 and geometric pieces reach ~70 marks TOTAL, so
        a mark-count floor would make the detector unreachable for the one era
        it exists to rescue — design invariant 1, in the fix for invariant 1.
        """
        assert SETTLED_MIN_MARKS > 70, "premise: the floor would exclude geometric"
        st = _frozen_state()
        canvas = _Canvas(marks=70)  # a whole cap-length geometric piece
        assert st.completion_reason(canvas) == "bailout_frozen"

    def test_idle_threshold_is_relative_to_the_pieces_own_rate(self):
        """A fixed 'fewer than N marks' would be unreachable for a slow era and
        constant for a fast one. 10% of own peak is neither."""
        assert 0.0 < FROZEN_FRAC_OF_PEAK < 1.0
        fast, slow = 200.0, 4.0
        assert fast * FROZEN_FRAC_OF_PEAK > slow  # a slow era's NORMAL rate
        # ...yet each is judged only against itself.
        assert slow * FROZEN_FRAC_OF_PEAK < 1.0


class TestFrozenIsNotEarned:

    def test_not_in_the_earned_set(self):
        """Nothing was resolved — the drawing got stuck. A bail-out must never
        become an 'I'm pleased with this drawing' memory."""
        assert "bailout_frozen" not in _EARNED_COMPLETION_REASONS
        assert is_earned_completion_reason("bailout_frozen") is False

    def test_earned_paths_still_win_when_both_apply(self):
        st = _frozen_state()
        st.curiosity = 0.1
        canvas = _Canvas()
        canvas.compositional_satisfaction = lambda: 0.9
        assert st.completion_reason(canvas) == "earned_composition"


class TestStructuralReachGuard:
    """occupied_cells() gets its first consumer.

    It was written to drawing_trajectory and drawing_records since #128 and read
    by nothing. Pixel novelty cannot tell a piece opening new territory from one
    thickening what it holds; cell count can.
    """

    # Novelty that starts high and collapses — the shape a settling piece has.
    # A flat novelty series can never advance the streak, because the smoothed
    # value IS the running peak and nothing is ever below a fraction of itself.
    NOVELTY = [100, 100, 100, 0, 0, 0, 0, 0, 0, 0]
    FLAT_CELLS = [20] * 10
    OPENING_CELLS = [4, 8, 12, 16, 20, 24, 28, 32, 36, 40]

    def _engine_tracker(self, cells_sequence, novelty=None):
        """Drive _update_novelty_settling over paired cell/novelty series."""
        from anima_mcp.display.drawing_engine import (
            DrawingEngine, TRAJECTORY_SAMPLE_INTERVAL,
        )
        novelty = self.NOVELTY if novelty is None else novelty
        engine = object.__new__(DrawingEngine)
        canvas = _Canvas()
        # Baselines must match the canvas, or the first sample reports the whole
        # canvas as one interval's growth.
        canvas._novelty_settling = {
            "last_t": 0.0, "last_px": 0, "last_marks": 0,
            "recent": [], "peak": 0.0, "streak": 0,
            "mark_peak": 0.0, "idle_streak": 0, "last_cells": 0,
        }
        engine.canvas = canvas
        px, marks, now = 0, 0, 0.0
        for cells, novel in zip(cells_sequence, novelty):
            px += novel
            marks += 10          # always actively worked: never an idle sample
            now += TRAJECTORY_SAMPLE_INTERVAL
            canvas.pixels = {i: 1 for i in range(px)}
            canvas.mark_count = marks
            canvas.occupied_cells = lambda c=cells: c
            engine._update_novelty_settling(now)
        return canvas._novelty_settling

    def test_opening_new_territory_resets_the_settled_streak(self):
        """Still reaching into empty ground is not settled, however slowly the
        pixel count is growing."""
        ns = self._engine_tracker(self.OPENING_CELLS)
        assert ns["streak"] == 0

    def test_flat_reach_lets_the_streak_accumulate(self):
        """Same near-zero novelty, but the piece has stopped finding cells."""
        ns = self._engine_tracker(self.FLAT_CELLS)
        assert ns["streak"] > 0

    def test_the_guard_can_only_subtract(self):
        """Strictly more conservative: it must never make earned_settled fire on
        a piece that would not otherwise have earned it."""
        flat = self._engine_tracker(self.FLAT_CELLS)["streak"]
        growing = self._engine_tracker(self.OPENING_CELLS)["streak"]
        assert growing <= flat

    def test_idle_advances_frozen_while_holding_settled(self):
        """The same sample means opposite things to the two counters — which is
        why they cannot share one."""
        from anima_mcp.display.drawing_engine import (
            DrawingEngine, TRAJECTORY_SAMPLE_INTERVAL,
        )
        engine = object.__new__(DrawingEngine)
        canvas = _Canvas()
        canvas.occupied_cells = lambda: 20
        canvas._novelty_settling = {
            # Baselines match the canvas, so every sample below is genuinely
            # idle rather than reporting the existing canvas as new growth.
            "last_t": 0.0, "last_px": len(canvas.pixels),
            "last_marks": canvas.mark_count,
            "recent": [], "peak": 0.0, "streak": 5,
            "mark_peak": 50.0, "idle_streak": 0, "last_cells": 20,
        }
        engine.canvas = canvas
        now = 0.0
        for _ in range(3):  # three fully idle samples: no marks at all
            now += TRAJECTORY_SAMPLE_INTERVAL
            engine._update_novelty_settling(now)
        ns = canvas._novelty_settling
        assert ns["idle_streak"] == 3, "frozen counter must advance on idle"
        assert ns["streak"] == 5, "settled streak must HOLD, not advance or reset"
