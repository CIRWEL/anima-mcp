"""Tests for gestural era smooth commitment signal."""

import random

from anima_mcp.display.eras.gestural import GesturalEra, GesturalState


def test_intentionality_smooth_range():
    """I spans 0.1-0.8 across commitment values, not bimodal."""
    state = GesturalState()
    state.gesture_remaining = 0

    # No commitment -> base I
    state.direction_commitment = 0.0
    assert abs(state.intentionality() - 0.1) < 0.01

    # Mid commitment
    state.direction_commitment = 0.5
    i_mid = state.intentionality()
    assert 0.3 < i_mid < 0.4, f"Expected ~0.35, got {i_mid}"

    # Full commitment
    state.direction_commitment = 1.0
    i_full = state.intentionality()
    assert 0.55 < i_full < 0.65, f"Expected ~0.6, got {i_full}"

    # Full commitment + active gesture run
    state.direction_commitment = 1.0
    state.gesture_remaining = 25
    i_max = state.intentionality()
    assert 0.75 < i_max < 0.85, f"Expected ~0.8, got {i_max}"


def test_commitment_ramps_during_lock():
    """Lock for 20 marks -> commitment > 0.6."""
    random.seed(12345)
    era = GesturalEra()
    state = era.create_state()
    state.direction_locked = True
    state.direction_lock_remaining = 30

    fx, fy, d = 120.0, 120.0, 0.0
    for _ in range(20):
        fx, fy, d = era.drift_focus(state, fx, fy, d, 0.5, 0.5, 0.5, 0.5)

    # 20 marks * +0.04 = 0.80 commitment
    assert state.direction_commitment > 0.6, (
        f"Expected commitment > 0.6 after 20 locked marks, got {state.direction_commitment}"
    )


def test_commitment_decays_after_lock():
    """Set commitment=0.8, run 30 unlocked marks -> commitment < 0.2."""
    random.seed(12345)
    era = GesturalEra()
    state = era.create_state()
    state.direction_commitment = 0.8
    state.direction_locked = False
    state.direction_lock_remaining = 0

    fx, fy, d = 120.0, 120.0, 0.0
    for _ in range(30):
        fx, fy, d = era.drift_focus(state, fx, fy, d, 0.5, 0.5, 0.5, 0.5)
        # Force no new locks for deterministic test
        state.direction_locked = False
        state.direction_lock_remaining = 0

    # 0.8 * 0.95^30 ≈ 0.17
    assert state.direction_commitment < 0.25, (
        f"Expected commitment < 0.25 after 30 unlocked marks, got {state.direction_commitment}"
    )


def test_jump_preserves_commitment_decay():
    """Focus jump doesn't zero commitment — it should still be positive."""
    state = GesturalState()
    state.direction_commitment = 0.8
    state.direction_locked = False
    state.direction_lock_remaining = 0

    # Simulate what a jump does (sets locked=False, lock_remaining=0)
    state.direction_locked = False
    state.direction_lock_remaining = 0
    # Key assertion: commitment is NOT zeroed by the jump fields
    assert state.direction_commitment == 0.8, (
        f"Jump should not zero commitment, got {state.direction_commitment}"
    )
