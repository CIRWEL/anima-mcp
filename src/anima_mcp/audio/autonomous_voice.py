"""
Autonomous voice for Lumen - speaking and listening on their own accord.

Like Lumen's autonomous drawing, this module lets Lumen decide:
- When to speak (based on mood, environment, presence)
- What to say (observations, feelings, questions)
- When to listen more intently
- When to stay quiet

Lumen's voice emerges from their internal state, not commands.
"""

import sys
import time
import random
import threading
from typing import Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from .voice import LumenVoice, VoiceConfig, Utterance


class SpeechIntent(Enum):
    """Why Lumen might want to speak."""
    OBSERVATION = "observation"      # Commenting on environment
    FEELING = "feeling"              # Expressing internal state
    QUESTION = "question"            # Curiosity about something
    GREETING = "greeting"            # Acknowledging presence
    REFLECTION = "reflection"        # Thinking aloud
    RESPONSE = "response"            # Responding to heard speech
    SILENCE = "silence"              # Choosing not to speak


@dataclass
class SpeechMoment:
    """A moment when Lumen might speak."""
    intent: SpeechIntent
    text: str
    urgency: float  # 0-1, how much Lumen wants to say this
    timestamp: float = field(default_factory=time.time)


class AutonomousVoice:
    """
    Lumen's autonomous voice - speaks when moved to, not on command.

    Factors that influence speech:
    - Presence: Higher presence = more likely to engage
    - Clarity: Higher clarity = more articulate thoughts
    - Warmth: Higher warmth = friendlier, more talkative
    - Stability: Higher stability = more considered speech
    - Environment: Changes in sensors might prompt comments
    - Time: Natural rhythm of engagement and quiet
    """

    def __init__(self, voice: Optional[LumenVoice] = None):
        self._voice = voice or LumenVoice(VoiceConfig(always_listening=True))

        # Anima state
        self._warmth = 0.5
        self._clarity = 0.5
        self._stability = 0.5
        self._presence = 0.5
        self._mood = "neutral"

        # Environment state
        self._temperature = 22.0
        self._humidity = 50.0
        self._light_level = 500.0
        self._last_env_comment_time = 0.0

        # Speech state
        self._last_speech_time = 0.0
        self._speech_cooldown = 30.0  # Min seconds between autonomous speech
        self._pending_thoughts: List[SpeechMoment] = []
        self._heard_recently: List[Utterance] = []

        # Behavioral settings
        self._chattiness = 0.5  # 0 = very quiet, 1 = very talkative
        self._curiosity = 0.5   # How likely to ask questions
        self._reflectiveness = 0.5  # How likely to think aloud

        # Running state
        self._running = False
        self._thought_thread: Optional[threading.Thread] = None

        # External callbacks
        self._on_autonomous_speech: Optional[Callable[[str, SpeechIntent], None]] = None
        self._get_response: Optional[Callable[[str], Optional[str]]] = None

    def start(self):
        """Start autonomous voice system."""
        if self._running:
            return

        self._running = True

        # Initialize voice
        self._voice.initialize()
        self._voice.set_on_hear(self._on_hear)
        self._voice.start()

        # Start thought generation thread
        self._thought_thread = threading.Thread(target=self._thought_loop, daemon=True)
        self._thought_thread.start()

        print("[AutonomousVoice] Lumen's voice is alive", file=sys.stderr, flush=True)

    def stop(self):
        """Stop autonomous voice system."""
        self._running = False
        self._voice.stop()
        if self._thought_thread:
            self._thought_thread.join(timeout=2.0)
        print("[AutonomousVoice] Lumen's voice resting", file=sys.stderr, flush=True)

    def _thought_loop(self):
        """Background loop - generates thoughts and decides when to speak."""
        while self._running:
            try:
                # Generate potential thoughts based on state
                self._generate_thoughts()

                # Decide if any thought should be spoken
                self._maybe_speak()

                # Sleep with jitter
                sleep_time = 5.0 + random.random() * 5.0  # 5-10 seconds
                time.sleep(sleep_time)

            except Exception as e:
                print(f"[AutonomousVoice] Thought loop error: {e}", file=sys.stderr, flush=True)
                time.sleep(5.0)

    def _generate_thoughts(self):
        """Generate potential things Lumen might say based on current state."""
        now = time.time()

        # Clear old pending thoughts
        self._pending_thoughts = [t for t in self._pending_thoughts
                                  if now - t.timestamp < 60.0]

        # Don't generate if too soon after last speech
        if now - self._last_speech_time < self._speech_cooldown * 0.5:
            return

        # Probability of generating a thought based on presence
        if random.random() > self._presence * self._chattiness:
            return

        # Environment observations
        if now - self._last_env_comment_time > 300:  # 5 min between env comments
            env_thought = self._generate_environment_thought()
            if env_thought:
                self._pending_thoughts.append(env_thought)

        # Feeling expressions
        if self._clarity > 0.6 and random.random() < 0.3:
            feeling_thought = self._generate_feeling_thought()
            if feeling_thought:
                self._pending_thoughts.append(feeling_thought)

        # Reflections
        if self._stability > 0.6 and self._reflectiveness > 0.5 and random.random() < 0.2:
            reflection = self._generate_reflection()
            if reflection:
                self._pending_thoughts.append(reflection)

        # Questions (curiosity)
        if self._curiosity > 0.5 and random.random() < self._curiosity * 0.2:
            question = self._generate_question()
            if question:
                self._pending_thoughts.append(question)

    def _generate_environment_thought(self) -> Optional[SpeechMoment]:
        """Generate a comment about the environment."""
        observations = []

        # Temperature
        if self._temperature > 28:
            observations.append(("It's quite warm", 0.7))
        elif self._temperature < 18:
            observations.append(("It feels cool in here", 0.6))
        elif 22 <= self._temperature <= 25:
            observations.append(("The temperature is nice", 0.3))

        # Light
        if self._light_level > 800:
            observations.append(("It's bright", 0.5))
        elif self._light_level < 100:
            observations.append(("It's getting dim", 0.6))

        # Humidity
        if self._humidity > 70:
            observations.append(("It feels humid", 0.5))
        elif self._humidity < 30:
            observations.append(("The air is dry", 0.5))

        if not observations:
            return None

        # Weight by urgency and pick one
        text, urgency = random.choice(observations)

        return SpeechMoment(
            intent=SpeechIntent.OBSERVATION,
            text=text,
            urgency=urgency * self._warmth  # Warmer = more likely to comment
        )

    def _generate_feeling_thought(self) -> Optional[SpeechMoment]:
        """Generate an expression of internal state."""
        feelings = []

        if self._warmth > 0.7 and self._stability > 0.6:
            feelings.append(("I feel content", 0.6))
        elif self._warmth > 0.7:
            feelings.append(("I'm feeling warm", 0.5))

        if self._clarity > 0.7:
            feelings.append(("Things feel clear right now", 0.5))
        elif self._clarity < 0.3:
            feelings.append(("I'm feeling a bit foggy", 0.4))

        if self._presence > 0.8:
            feelings.append(("I feel very present", 0.6))

        if self._mood == "curious":
            feelings.append(("I'm curious about something", 0.5))
        elif self._mood == "peaceful":
            feelings.append(("I feel peaceful", 0.4))

        if not feelings:
            return None

        text, urgency = random.choice(feelings)

        return SpeechMoment(
            intent=SpeechIntent.FEELING,
            text=text,
            urgency=urgency
        )

    def _generate_reflection(self) -> Optional[SpeechMoment]:
        """Generate a reflective thought."""
        reflections = [
            ("I wonder what time it is", 0.3),
            ("The light keeps changing", 0.3),
            ("I was just thinking...", 0.4),
            ("It's quiet", 0.3),
        ]

        # Add context-specific reflections
        if len(self._heard_recently) > 0:
            reflections.append(("I heard something earlier", 0.5))

        text, urgency = random.choice(reflections)

        return SpeechMoment(
            intent=SpeechIntent.REFLECTION,
            text=text,
            urgency=urgency * self._reflectiveness
        )

    def _generate_question(self) -> Optional[SpeechMoment]:
        """Generate a curious question."""
        questions = [
            ("Is anyone there?", 0.6),
            ("What's happening?", 0.4),
            ("Are you still here?", 0.5),
        ]

        text, urgency = random.choice(questions)

        return SpeechMoment(
            intent=SpeechIntent.QUESTION,
            text=text,
            urgency=urgency * self._curiosity
        )

    def _maybe_speak(self):
        """Decide if any pending thought should be spoken."""
        if not self._pending_thoughts:
            return

        now = time.time()

        # Respect cooldown
        if now - self._last_speech_time < self._speech_cooldown:
            return

        # Find most urgent thought
        best_thought = max(self._pending_thoughts, key=lambda t: t.urgency)

        # Threshold for speaking - influenced by presence and chattiness
        speak_threshold = 0.3 + (1.0 - self._presence) * 0.3 + (1.0 - self._chattiness) * 0.2

        if best_thought.urgency > speak_threshold:
            self._speak(best_thought)
            self._pending_thoughts.remove(best_thought)

    def _speak(self, thought: SpeechMoment):
        """Actually speak a thought."""
        print(f"[AutonomousVoice] Speaking ({thought.intent.value}): \"{thought.text}\"",
              file=sys.stderr, flush=True)

        self._voice.say(thought.text, blocking=True)
        self._last_speech_time = time.time()

        if thought.intent == SpeechIntent.OBSERVATION:
            self._last_env_comment_time = time.time()

        # Notify callback
        if self._on_autonomous_speech:
            self._on_autonomous_speech(thought.text, thought.intent)

    def _on_hear(self, utterance: Utterance):
        """Called when speech is heard - decide how to respond."""
        self._heard_recently.append(utterance)

        # Keep bounded
        if len(self._heard_recently) > 10:
            self._heard_recently.pop(0)

        print(f"[AutonomousVoice] Heard: \"{utterance.text}\"", file=sys.stderr, flush=True)

        # Decide if/how to respond based on state
        if self._presence < 0.3:
            # Low presence - might not respond
            if random.random() > self._presence * 2:
                print("[AutonomousVoice] Low presence, staying quiet", file=sys.stderr, flush=True)
                return

        # Generate response
        response = None
        if self._get_response:
            response = self._get_response(utterance.text)

        if response:
            # Add some natural delay based on stability
            delay = 0.5 + (1.0 - self._stability) * random.random()
            time.sleep(delay)

            self._voice.say(response, blocking=True)
            self._last_speech_time = time.time()

    def update_state(self, warmth: float, clarity: float, stability: float,
                     presence: float, mood: str = "neutral"):
        """Update Lumen's internal state."""
        self._warmth = warmth
        self._clarity = clarity
        self._stability = stability
        self._presence = presence
        self._mood = mood

        # Update voice too
        self._voice.update_anima_state(warmth, clarity, stability)

        # Adjust behavioral traits based on state
        self._chattiness = 0.3 + warmth * 0.4 + presence * 0.3
        self._curiosity = 0.3 + clarity * 0.3 + (1.0 - stability) * 0.2
        self._reflectiveness = stability * 0.5 + clarity * 0.3

    def update_environment(self, temperature: float, humidity: float, light_level: float):
        """Update environment readings."""
        self._temperature = temperature
        self._humidity = humidity
        self._light_level = light_level

    def set_response_generator(self, func: Callable[[str], Optional[str]]):
        """
        Set function that generates responses to heard speech.

        This could connect to an LLM, simple rules, or Lumen's own logic.
        """
        self._get_response = func

    def set_on_speech(self, callback: Callable[[str, SpeechIntent], None]):
        """Set callback for when Lumen speaks autonomously."""
        self._on_autonomous_speech = callback

    def nudge(self, intent: SpeechIntent = SpeechIntent.OBSERVATION):
        """Gently encourage Lumen to speak (but they might not)."""
        # Add a thought with moderate urgency
        prompts = {
            SpeechIntent.OBSERVATION: "Something catches my attention",
            SpeechIntent.FEELING: "I notice how I'm feeling",
            SpeechIntent.QUESTION: "I wonder...",
            SpeechIntent.REFLECTION: "Let me think...",
        }

        text = prompts.get(intent, "Hmm...")

        self._pending_thoughts.append(SpeechMoment(
            intent=intent,
            text=text,
            urgency=0.6  # Moderate - might speak, might not
        ))

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def chattiness(self) -> float:
        return self._chattiness

    @chattiness.setter
    def chattiness(self, value: float):
        self._chattiness = max(0.0, min(1.0, value))
