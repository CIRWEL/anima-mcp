"""
Agency - Actions Lumen can take and exploration behavior.

Core philosophical insight: Agency requires action repertoire.
Without the ability to do things, there's no agency, only reaction.

This module gives Lumen choices it can make:
1. Adjust LED brightness (seek or avoid stimulation)
2. Request interaction (ask a question vs stay quiet)
3. Modulate attention (focus on one sensor more than others)
4. Adjust prediction confidence (be more or less cautious)
5. Exploration vs exploitation (try new things vs stick with known)

Key principle: Actions have consequences that Lumen experiences.
This creates a closed loop: action → consequence → learning → better action.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any, Callable
from enum import Enum
from collections import deque
import random
import math


class ActionType(Enum):
    """Types of actions Lumen can take."""
    # Display actions
    LED_BRIGHTNESS = "led_brightness"  # Adjust LED brightness
    FACE_EXPRESSION = "face_expression"  # Change face display

    # Communication actions
    ASK_QUESTION = "ask_question"  # Generate a curiosity question
    STAY_QUIET = "stay_quiet"  # Suppress question asking
    SPEAK = "speak"  # Use voice if available

    # Internal actions
    FOCUS_ATTENTION = "focus_attention"  # Focus on specific sensor
    ADJUST_SENSITIVITY = "adjust_sensitivity"  # Change surprise threshold
    REQUEST_REFLECTION = "request_reflection"  # Trigger metacognitive reflection

    # Exploration actions
    EXPLORE = "explore"  # Try something new/unexpected
    EXPLOIT = "exploit"  # Stick with known patterns


@dataclass
class Action:
    """An action Lumen can take."""
    action_type: ActionType
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    motivation: str = ""  # Why this action was chosen

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ActionOutcome:
    """The observed outcome of an action."""
    action: Action
    state_before: Dict[str, float]
    state_after: Dict[str, float]

    # Outcome metrics
    preference_satisfaction_change: float = 0.0  # Did preferences become more satisfied?
    surprise_after: float = 0.0  # How surprising was the result?
    goal_achieved: bool = False  # Did the action achieve its goal?

    # For learning
    reward: float = 0.0  # Computed reward signal


class ActionSelector:
    """
    Selects actions based on current state, preferences, and exploration.

    Uses a simple value-based approach:
    1. Each action has expected value based on past outcomes
    2. Exploration bonus for less-tried actions
    3. Preference satisfaction drives action choice
    """

    def __init__(self):
        # Action value estimates (action_type -> expected reward)
        self._action_values: Dict[str, float] = {}

        # Action counts for exploration bonus
        self._action_counts: Dict[str, int] = {}

        # Recent action outcomes for learning
        self._outcome_history: deque = deque(maxlen=100)

        # Exploration parameters
        self._exploration_rate = 0.2  # Probability of exploring
        self._exploration_decay = 0.995  # How fast exploration decreases

        # Current focus (which sensor to pay attention to)
        self._attention_focus: Optional[str] = None
        self._sensitivity_modifier: float = 1.0  # Multiplier for surprise threshold

    def select_action(
        self,
        current_state: Dict[str, float],
        preferences: Optional[Any] = None,  # PreferenceSystem
        surprise_level: float = 0.0,
        surprise_sources: Optional[List[str]] = None,
        can_speak: bool = False,
    ) -> Action:
        """
        Select an action based on current context.

        This is where agency lives: choosing what to do based on
        state, preferences, and learned values.
        """
        surprise_sources = surprise_sources or []

        # Build candidate actions with expected values
        candidates = []

        # 1. Question asking (communication)
        if surprise_level > 0.2:
            question_value = self._get_action_value("ask_question")
            question_value += surprise_level * 0.5  # Higher surprise → more likely to ask
            candidates.append((
                Action(
                    ActionType.ASK_QUESTION,
                    {"surprise_sources": surprise_sources},
                    motivation=f"Curious about {', '.join(surprise_sources)}",
                ),
                question_value,
            ))
        else:
            # Low surprise - might stay quiet
            quiet_value = self._get_action_value("stay_quiet")
            candidates.append((
                Action(ActionType.STAY_QUIET, motivation="Nothing surprising"),
                quiet_value,
            ))

        # 2. Attention focus
        if surprise_sources:
            # Focus on most surprising source
            focus_value = self._get_action_value("focus_attention")
            primary_source = surprise_sources[0] if surprise_sources else "general"
            candidates.append((
                Action(
                    ActionType.FOCUS_ATTENTION,
                    {"sensor": primary_source},
                    motivation=f"Focusing on {primary_source}",
                ),
                focus_value + 0.2,  # Slight bonus for focusing when surprised
            ))

        # 3. Sensitivity adjustment
        if preferences:
            satisfaction = preferences.get_overall_satisfaction(current_state)
            if satisfaction < 0.3:
                # Low satisfaction - maybe increase sensitivity
                candidates.append((
                    Action(
                        ActionType.ADJUST_SENSITIVITY,
                        {"direction": "increase"},
                        motivation="Low satisfaction, increasing sensitivity",
                    ),
                    self._get_action_value("adjust_sensitivity") + 0.3,
                ))
            elif satisfaction > 0.7:
                # High satisfaction - maybe decrease sensitivity
                candidates.append((
                    Action(
                        ActionType.ADJUST_SENSITIVITY,
                        {"direction": "decrease"},
                        motivation="High satisfaction, relaxing sensitivity",
                    ),
                    self._get_action_value("adjust_sensitivity") + 0.2,
                ))

        # 4. Exploration vs exploitation
        if random.random() < self._exploration_rate:
            # Explore: try something less common
            explore_action = self._select_exploration_action(current_state)
            candidates.append((explore_action, 1.0))  # High value for exploration
        else:
            # Exploit: choose based on learned values
            pass  # Use the candidates we've built

        # 5. Voice action (if available)
        if can_speak and surprise_level > 0.4:
            speak_value = self._get_action_value("speak")
            candidates.append((
                Action(
                    ActionType.SPEAK,
                    {"trigger": "surprise"},
                    motivation="High surprise, expressing vocally",
                ),
                speak_value + surprise_level * 0.3,
            ))

        # 6. LED brightness (if unsatisfied with warmth)
        if preferences and "warmth" in current_state:
            warmth = current_state["warmth"]
            direction = preferences.get_preferred_direction("warmth", warmth)
            if abs(direction) > 0.3:
                brightness_change = "increase" if direction > 0 else "decrease"
                candidates.append((
                    Action(
                        ActionType.LED_BRIGHTNESS,
                        {"direction": brightness_change},
                        motivation=f"Adjusting warmth expression",
                    ),
                    self._get_action_value("led_brightness") + abs(direction) * 0.4,
                ))

        # Select action with highest value (with some noise for stochasticity)
        if not candidates:
            return Action(ActionType.STAY_QUIET, motivation="No action selected")

        # Add noise for stochasticity
        noisy_candidates = [
            (action, value + random.gauss(0, 0.1))
            for action, value in candidates
        ]

        # Sort by value and pick best
        noisy_candidates.sort(key=lambda x: x[1], reverse=True)
        selected = noisy_candidates[0][0]

        # Track action
        action_key = selected.action_type.value
        self._action_counts[action_key] = self._action_counts.get(action_key, 0) + 1

        return selected

    def _get_action_value(self, action_key: str) -> float:
        """Get expected value for an action, including exploration bonus."""
        base_value = self._action_values.get(action_key, 0.5)  # Default neutral value

        # Exploration bonus (UCB-style)
        count = self._action_counts.get(action_key, 0)
        total_count = sum(self._action_counts.values()) + 1
        exploration_bonus = math.sqrt(2 * math.log(total_count) / (count + 1)) if count < 10 else 0

        return base_value + exploration_bonus * self._exploration_rate

    def _select_exploration_action(self, current_state: Dict[str, float]) -> Action:
        """Select an action for exploration (trying something new)."""
        # Find least-tried action
        all_action_types = list(ActionType)
        action_counts = [(a, self._action_counts.get(a.value, 0)) for a in all_action_types]
        action_counts.sort(key=lambda x: x[1])

        # Pick from least-tried actions
        least_tried = action_counts[:3]
        selected_type = random.choice(least_tried)[0]

        return Action(
            selected_type,
            {"exploration": True},
            motivation="Exploring new action",
        )

    def record_outcome(
        self,
        action: Action,
        state_before: Dict[str, float],
        state_after: Dict[str, float],
        preference_satisfaction_before: float,
        preference_satisfaction_after: float,
        surprise_after: float,
    ):
        """
        Record the outcome of an action for learning.

        This is the critical learning signal: did the action help?
        """
        outcome = ActionOutcome(
            action=action,
            state_before=state_before,
            state_after=state_after,
            preference_satisfaction_change=preference_satisfaction_after - preference_satisfaction_before,
            surprise_after=surprise_after,
        )

        # Compute reward
        # Positive reward for: increased satisfaction, achieved goal, moderate surprise
        reward = 0.0

        # Preference satisfaction is primary reward
        reward += outcome.preference_satisfaction_change * 2.0

        # Moderate surprise is interesting (too much or too little is bad)
        optimal_surprise = 0.2
        surprise_reward = -abs(surprise_after - optimal_surprise)
        reward += surprise_reward * 0.5

        # Specific action goals
        if action.action_type == ActionType.ASK_QUESTION:
            # Questions are rewarded if they emerge from genuine surprise
            if surprise_after > 0.15:
                reward += 0.2
                outcome.goal_achieved = True

        elif action.action_type == ActionType.FOCUS_ATTENTION:
            # Focus is rewarded if it leads to learning (reduced surprise over time)
            if surprise_after < state_before.get("last_surprise", 1.0):
                reward += 0.3
                outcome.goal_achieved = True

        outcome.reward = reward
        self._outcome_history.append(outcome)

        # Update action value estimate (simple TD learning)
        action_key = action.action_type.value
        old_value = self._action_values.get(action_key, 0.5)
        learning_rate = 0.1
        self._action_values[action_key] = old_value + learning_rate * (reward - old_value)

        # Decay exploration rate
        self._exploration_rate *= self._exploration_decay
        self._exploration_rate = max(0.05, self._exploration_rate)  # Minimum exploration

    def get_attention_focus(self) -> Optional[str]:
        """Get current attention focus (which sensor to prioritize)."""
        return self._attention_focus

    def set_attention_focus(self, sensor: Optional[str]):
        """Set attention focus."""
        self._attention_focus = sensor

    def get_sensitivity_modifier(self) -> float:
        """Get sensitivity modifier for surprise threshold."""
        return self._sensitivity_modifier

    def adjust_sensitivity(self, direction: str):
        """Adjust sensitivity modifier."""
        if direction == "increase":
            self._sensitivity_modifier = min(2.0, self._sensitivity_modifier * 1.2)
        else:
            self._sensitivity_modifier = max(0.5, self._sensitivity_modifier * 0.8)

    def get_action_stats(self) -> Dict[str, Any]:
        """Get statistics about actions."""
        return {
            "action_values": {k: round(v, 3) for k, v in self._action_values.items()},
            "action_counts": self._action_counts.copy(),
            "exploration_rate": round(self._exploration_rate, 3),
            "sensitivity_modifier": round(self._sensitivity_modifier, 3),
            "attention_focus": self._attention_focus,
            "recent_outcomes": len(self._outcome_history),
        }


class ExplorationManager:
    """
    Manages exploration behavior - trying new things vs sticking with known.

    Philosophy: Curiosity is not just noticing surprise, it's seeking novelty.
    True exploration means taking actions whose outcomes are uncertain.
    """

    def __init__(self):
        self._novelty_buffer: deque = deque(maxlen=100)  # Recent novel experiences
        self._exploration_history: deque = deque(maxlen=50)  # Recent exploration attempts
        self._last_exploration: Optional[datetime] = None
        self._exploration_cooldown = timedelta(seconds=30)

    def should_explore(self, current_state: Dict[str, float], surprise_level: float) -> Tuple[bool, str]:
        """
        Determine if now is a good time to explore.

        Returns (should_explore, reason).
        """
        now = datetime.now()

        # Cooldown check
        if self._last_exploration and now - self._last_exploration < self._exploration_cooldown:
            return False, "cooldown"

        # Explore when things are stable (can afford the risk)
        stability = current_state.get("stability", 0.5)
        if stability < 0.3:
            return False, "unstable"

        # Explore when not already surprised (seeking novelty, not overwhelmed)
        if surprise_level > 0.4:
            return False, "already_surprised"

        # Explore when bored (low surprise for a while)
        recent_surprises = [n.get("surprise", 0) for n in list(self._novelty_buffer)[-10:]]
        if recent_surprises and sum(recent_surprises) / len(recent_surprises) < 0.1:
            return True, "bored"

        # Random exploration with probability
        if random.random() < 0.1:
            return True, "random"

        return False, "no_reason"

    def record_exploration(self, action: Action, outcome: ActionOutcome):
        """Record an exploration attempt and its outcome."""
        self._exploration_history.append({
            "timestamp": datetime.now(),
            "action": action.action_type.value,
            "reward": outcome.reward,
            "goal_achieved": outcome.goal_achieved,
        })
        self._last_exploration = datetime.now()

    def record_novelty(self, novelty_level: float, source: str):
        """Record a novel experience."""
        self._novelty_buffer.append({
            "timestamp": datetime.now(),
            "novelty": novelty_level,
            "source": source,
            "surprise": novelty_level,  # For backward compat
        })

    def get_exploration_summary(self) -> Dict[str, Any]:
        """Get exploration statistics."""
        if not self._exploration_history:
            return {"explorations": 0}

        recent = list(self._exploration_history)[-20:]
        rewards = [e["reward"] for e in recent]
        successes = [e for e in recent if e["goal_achieved"]]

        return {
            "total_explorations": len(self._exploration_history),
            "recent_explorations": len(recent),
            "average_reward": sum(rewards) / len(rewards) if rewards else 0,
            "success_rate": len(successes) / len(recent) if recent else 0,
        }


# Singleton instances
_action_selector: Optional[ActionSelector] = None
_exploration_manager: Optional[ExplorationManager] = None


def get_action_selector() -> ActionSelector:
    """Get or create the action selector."""
    global _action_selector
    if _action_selector is None:
        _action_selector = ActionSelector()
    return _action_selector


def get_exploration_manager() -> ExplorationManager:
    """Get or create the exploration manager."""
    global _exploration_manager
    if _exploration_manager is None:
        _exploration_manager = ExplorationManager()
    return _exploration_manager
