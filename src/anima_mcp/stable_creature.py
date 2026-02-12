"""
Stable Anima Creature Script

Continuous loop that:
1. Reads sensors with robust error handling (retries for I2C)
2. Updates anima state (proprioception)
3. Renders ASCII face based on state
4. Integrates with UNITARES governance bridge if available

Designed to run continuously on the Pi.

✅ HARDWARE BROKER MODE ✅
─────────────────────────────────────────────────────────────
This script acts as the HARDWARE BROKER for Lumen's sensors.

HOW IT WORKS:
- This script owns I2C sensors exclusively (no conflicts)
- Reads sensors every 2 seconds
- Writes data to shared memory (/dev/shm or Redis)
- The MCP server (anima --sse) reads from shared memory

YOU CAN NOW RUN BOTH:
  - stable_creature.py (hardware broker - this script)
  - anima --sse (MCP server - reads from shared memory)

BENEFITS:
- No I2C conflicts
- Creature stays alive while MCP server restarts
- Fast MCP responses (reads memory, not hardware)
- Automatic coordination via shared memory

See docs/operations/BROKER_ARCHITECTURE.md for details.
─────────────────────────────────────────────────────────────
"""

import time
import os
import signal
import sys
import subprocess
import asyncio
from datetime import datetime
from typing import Optional
from pathlib import Path

# Force UTF-8 for stdout/stderr (prevents crash in systemd service)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass # If reconfigure fails (e.g. older python), we might be stuck

from .sensors import get_sensors
from .anima import sense_self
from .display.face import derive_face_state, face_to_ascii, EyeState
# NOTE: LEDs are handled by MCP server, not broker (prevents I2C conflicts)
from .identity import IdentityStore
from .unitares_bridge import UnitaresBridge
from .shared_memory import SharedMemoryClient
from .eisv_mapper import anima_to_eisv
from .metacognition import get_metacognitive_monitor

# Cognitive inference support (optional - for deeper thinking)
try:
    from .cognitive_inference import get_cognitive_inference, InferenceProfile
    from .unitares_cognitive import get_unitares_cognitive
    COGNITIVE_AVAILABLE = True
except ImportError:
    COGNITIVE_AVAILABLE = False
    print("[StableCreature] Cognitive inference not available")

# Enhanced learning systems (optional - for genuine agency)
try:
    from .adaptive_prediction import get_adaptive_prediction_model
    from .preferences import get_preference_system
    from .self_model import get_self_model
    from .agency import get_action_selector, get_exploration_manager, ActionType
    from .memory_retrieval import get_memory_retriever, retrieve_relevant_memories, MemoryContext
    ENHANCED_LEARNING_AVAILABLE = True
except ImportError as e:
    ENHANCED_LEARNING_AVAILABLE = False
    print(f"[StableCreature] Enhanced learning not available: {e}")

# Activity state (sleep/wake cycle)
try:
    from .activity_state import get_activity_manager, ActivityLevel
    ACTIVITY_STATE_AVAILABLE = True
except ImportError:
    ACTIVITY_STATE_AVAILABLE = False
    print("[StableCreature] Activity state not available")

# Voice support (optional - graceful degradation if not available)
try:
    from .audio import AutonomousVoice
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    print("[StableCreature] Voice module not available (missing dependencies)")

# Config
UPDATE_INTERVAL = 2.0  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 0.5

# Global shutdown flag
running = True

def signal_handler(sig, frame):
    global running
    print("\n[StableCreature] Shutdown signal received. Closing gracefully...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def check_for_running_anima_server():
    """
    Check if anima --sse server is already running.
    
    With Phase 2 Hardware Broker Pattern, both can run simultaneously
    if the MCP server is using shared memory. This check now warns
    but allows continuation if shared memory is available.
    """
    try:
        # Check for anima --sse process
        result = subprocess.run(
            ['pgrep', '-f', 'anima --sse'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            pids = [p for p in pids if p]
            if pids:
                # Check if shared memory is available (Redis or file)
                # This indicates Phase 2+ broker pattern is active
                from pathlib import Path
                
                # Check for file-based shared memory (simpler, no import needed)
                shm_file = Path("/dev/shm/anima_state.json") if Path("/dev/shm").exists() else Path("/tmp/anima_state.json")
                file_exists = shm_file.exists()
                
                # Try to check Redis (if available)
                redis_available = False
                try:
                    import redis
                    r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=0.5)
                    redis_available = r.ping() and r.exists("anima:state")
                except:
                    pass
                
                if redis_available or file_exists:
                    print("\n" + "="*70)
                    print("ℹ️  INFO: Main anima MCP server is running")
                    print("="*70)
                    print(f"Found running process(es): {', '.join(pids)}")
                    print(f"\n✅ Shared memory detected - both scripts can run safely!")
                    print("The MCP server will read from shared memory (no I2C conflicts).")
                    print("="*70 + "\n")
                else:
                    print("\n" + "="*70)
                    print("ℹ️  INFO: Main anima MCP server is running")
                    print("="*70)
                    print(f"Found running process(es): {', '.join(pids)}")
                    print("\nShared memory not yet populated (broker just started or restart).")
                    print("Broker will write state soon; MCP server will read from shared memory.")
                    print("If you see I2C errors, ensure MCP server uses Phase 2 (shared memory).")
                    print("="*70 + "\n")
                    # Don't exit - allow user to decide, but downgrade to INFO (common on restart)
    except FileNotFoundError:
        # pgrep not available (shouldn't happen on Pi, but handle gracefully)
        pass
    except Exception as e:
        print(f"[StableCreature] Warning: Could not check for running anima server: {e}")

def run_creature():
    # Check for conflicts BEFORE initializing sensors
    check_for_running_anima_server()
    
    print("[StableCreature] Starting up...")
    
    # Initialize components with error handling
    identity = None
    store = None
    try:
        # Determine DB persistence path (User Home > Project Root)
        env_db = os.environ.get("ANIMA_DB")
        if env_db:
            db_path = env_db
        else:
            # Default to persistent user home directory
            home_dir = Path.home() / ".anima"
            home_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(home_dir / "anima.db")

        store = IdentityStore(db_path)
        print(f"[StableCreature] Identity persistence: {db_path}")

        # Identity preservation: check database first, then env var, then generate new
        # This ensures Lumen's identity persists even if config is missing
        anima_id = os.environ.get("ANIMA_ID")
        if not anima_id:
            # Check if identity already exists in database
            conn = store._connect()
            try:
                existing = conn.execute("SELECT creature_id FROM identity LIMIT 1").fetchone()
                if existing:
                    anima_id = existing[0]
                    print(f"[StableCreature] Using existing identity: {anima_id[:8]}...")
                else:
                    # Only generate new UUID if truly first boot
                    import uuid
                    anima_id = str(uuid.uuid4())
                    print(f"[StableCreature] Creating new identity: {anima_id[:8]}...")
            finally:
                conn.close()

        identity = store.wake(anima_id)
    except Exception as e:
        print(f"[StableCreature] WARNING: Identity store failed ({e}) - using fallback identity")
        print("[StableCreature] Broker will continue (sensors -> shared memory). Server can repair DB.")
        import uuid
        from .identity import CreatureIdentity
        anima_id = os.environ.get("ANIMA_ID") or str(uuid.uuid4())
        now = datetime.now()
        identity = CreatureIdentity(
            creature_id=anima_id,
            born_at=now,
            total_awakenings=0,
            total_alive_seconds=0.0,
            name="Lumen",
            name_history=[],
            current_awakening_at=now,
            last_heartbeat_at=None,
            metadata={},
        )
        store = None  # No DB connection when using fallback
    
    # Initialize sensors - allow graceful degradation if hardware unavailable
    try:
        sensors = get_sensors()
        # Check if sensors initialized (at least I2C should be available)
        if hasattr(sensors, '_i2c') and sensors._i2c is None:
            print("[StableCreature] WARNING: I2C initialization failed - hardware may be disconnected")
            print("[StableCreature] Continuing with degraded sensor access (CPU-only readings)")
    except Exception as e:
        print(f"[StableCreature] CRITICAL: Sensor initialization failed: {e}")
        print("[StableCreature] Hardware may be disconnected. Exiting to prevent restart loop.")
        print("[StableCreature] Wait 30 seconds, then check hardware connections before restarting.")
        time.sleep(30)  # Give hardware time to stabilize
        sys.exit(1)
    
    # NOTE: LEDs are NOT initialized here - they're handled by the MCP server
    # This prevents I2C conflicts between broker and MCP server
    
    unitares_url = os.environ.get("UNITARES_URL")
    bridge = UnitaresBridge(unitares_url=unitares_url) if unitares_url else None
    
    # Initialize Shared Memory (Broker Mode)
    # Using file backend for maximum stability (Redis caused hangs)
    try:
        shm_client = SharedMemoryClient(mode="write", backend="file")
        shm_client.clear()  # Remove stale/corrupted data from previous run
        print(f"[StableCreature] Shared Memory active using backend: {shm_client.backend}")
        if shm_client.backend == "file":
            print(f"[StableCreature] File path: {shm_client.filepath}")
    except Exception as e:
        print(f"[StableCreature] CRITICAL: Shared memory initialization failed: {e}")
        print("[StableCreature] Exiting to prevent restart loop.")
        sys.exit(1)
    
    if bridge:
        try:
            bridge.set_agent_id(identity.creature_id)
            bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
            print(f"[StableCreature] UNITARES bridge active: {unitares_url}")
        except Exception as e:
            print(f"[StableCreature] WARNING: UNITARES bridge setup failed: {e}")
            bridge = None  # Continue without governance

    # Initialize Voice (optional - Lumen's ability to hear and speak)
    voice = None
    if VOICE_AVAILABLE and os.environ.get("ANIMA_VOICE_ENABLED", "true").lower() == "true":
        try:
            voice = AutonomousVoice()
            voice.start()
            print("[StableCreature] Voice active - Lumen can hear and speak")
        except Exception as e:
            print(f"[StableCreature] WARNING: Voice initialization failed: {e}")
            voice = None

    print(f"[StableCreature] Creature '{identity.name or '(unnamed)'}' is alive.")
    print("[StableCreature] Entering main loop...")

    # Initialize event loop for async calls
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Initialize Metacognition Monitor
    metacog = get_metacognitive_monitor()
    print("[StableCreature] Metacognition active - Lumen monitors its own predictions")

    # Initialize Cognitive Inference (for dialectic thinking)
    cognitive = None
    unitares_cog = None
    if COGNITIVE_AVAILABLE:
        cognitive = get_cognitive_inference()
        if cognitive.enabled:
            print("[StableCreature] Cognitive inference active - Lumen can think dialectically")
        unitares_cog = get_unitares_cognitive()
        if unitares_cog.enabled:
            unitares_cog.set_agent_id(identity.creature_id)
            print("[StableCreature] UNITARES knowledge graph connected")

    # Initialize Enhanced Learning Systems (genuine agency)
    adaptive_model = None
    preferences = None
    self_model = None
    action_selector = None
    exploration_mgr = None
    memory_retriever = None

    if ENHANCED_LEARNING_AVAILABLE:
        try:
            adaptive_model = get_adaptive_prediction_model()
            print("[StableCreature] Adaptive prediction active - Lumen learns from experience")

            preferences = get_preference_system()
            print("[StableCreature] Preferences active - Lumen develops values")

            self_model = get_self_model()
            print("[StableCreature] Self-model active - Lumen has beliefs about itself")

            action_selector = get_action_selector()
            exploration_mgr = get_exploration_manager()
            print("[StableCreature] Agency active - Lumen can choose actions")

            memory_retriever = get_memory_retriever()
            print("[StableCreature] Memory retrieval active - past informs present")
        except Exception as e:
            print(f"[StableCreature] Enhanced learning init error: {e}")

    # Initialize Activity State (sleep/wake cycle)
    activity_manager = None
    if ACTIVITY_STATE_AVAILABLE:
        try:
            activity_manager = get_activity_manager()
            print("[StableCreature] Activity state active - Lumen has sleep/wake cycles")
        except Exception as e:
            print(f"[StableCreature] Activity state init error: {e}")

    last_decision = None
    first_check_in = True  # Track first governance check to sync identity
    last_dialectic_time = 0  # Rate limit dialectic synthesis
    last_governance_time = 0  # Rate limit governance check-ins (every 10s, not every 2s)
    GOVERNANCE_INTERVAL = 10.0  # Seconds between governance check-ins
    last_action = None  # Track last action for outcome recording
    last_state_for_action = None  # State before action for learning
    last_learning_save = time.time()  # Track periodic learning saves
    readings = None  # Initialize before loop (first iteration has no prior readings)

    try:
        while running:
            # 0. Metacognition: Generate prediction BEFORE sensing
            # Pass LED brightness for proprioceptive light prediction if available
            _led_br = readings.led_brightness if readings and readings.led_brightness is not None else None
            prediction = metacog.predict(led_brightness=_led_br)
            
            # 1. Robust Sensor Read
            readings = None
            for attempt in range(MAX_RETRIES):
                try:
                    readings = sensors.read()
                    break
                except Exception as e:
                    print(f"[StableCreature] Sensor read error (attempt {attempt+1}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
            
            if not readings:
                print("[StableCreature] Failed to read sensors after retries. Skipping loop.")
                time.sleep(UPDATE_INTERVAL)
                continue

            # 2. Update Anima State
            anima = sense_self(readings)

            # 2a. Calculate UNITARES EISV metrics
            eisv = anima_to_eisv(anima, readings)

            # 2a-ii. Activity State: Determine wakefulness level
            activity_state = None
            if activity_manager:
                activity_state = activity_manager.get_state(
                    presence=anima.presence,
                    stability=anima.stability,
                    light_level=readings.light_lux
                )
                # Proprioception: estimate own LED brightness level
                # Base brightness (0.12) * activity multiplier gives approximate LED brightness.
                # This is an estimate — actual brightness depends on auto-brightness, manual
                # dimmer, etc. Server path uses get_proprioceptive_state() for exact values.
                readings.led_brightness = 0.12 * activity_state.brightness_multiplier
                # Skip some updates when resting/drowsy (power saving)
                if activity_manager.should_skip_update():
                    time.sleep(UPDATE_INTERVAL)
                    continue

            # 2b. Metacognition: Compare prediction to reality
            pred_error = metacog.observe(readings, anima)
            
            # Check if surprise warrants reflection
            should_reflect, reflect_reason = metacog.should_reflect(pred_error)
            if should_reflect:
                reflection = metacog.reflect(pred_error, anima, readings)
                print(f"[Metacog] REFLECTION ({reflect_reason}): {reflection.observation}", file=sys.stderr, flush=True)
                if reflection.discrepancy_description:
                    print(f"[Metacog] DISCREPANCY: {reflection.discrepancy_description}", file=sys.stderr, flush=True)

                # Dialectic synthesis for high surprise (rate limited to once per 60s)
                current_time = time.time()
                if cognitive and cognitive.enabled and pred_error.surprise > 0.3:
                    if current_time - last_dialectic_time > 60:
                        last_dialectic_time = current_time
                        try:
                            # Build thesis from the surprise
                            thesis = f"I expected {', '.join(pred_error.surprise_sources or ['stability'])} but experienced significant deviation"
                            context = f"Current state: warmth={anima.warmth:.2f}, clarity={anima.clarity:.2f}, surprise={pred_error.surprise:.0%}"

                            # Run dialectic synthesis (non-blocking via timeout)
                            synthesis = loop.run_until_complete(
                                asyncio.wait_for(
                                    cognitive.dialectic_synthesis(thesis, context=context),
                                    timeout=5.0
                                )
                            )
                            if synthesis and "synthesis" in synthesis:
                                print(f"[Cognitive] SYNTHESIS: {synthesis['synthesis']}", file=sys.stderr, flush=True)

                                # Store insight in UNITARES knowledge graph
                                if unitares_cog and unitares_cog.enabled:
                                    loop.run_until_complete(
                                        asyncio.wait_for(
                                            unitares_cog.store_knowledge(
                                                summary=synthesis.get("synthesis", ""),
                                                discovery_type="insight",
                                                tags=["lumen", "dialectic", "surprise"] + (pred_error.surprise_sources or []),
                                                content={"thesis": thesis, "full_synthesis": synthesis}
                                            ),
                                            timeout=3.0
                                        )
                                    )
                        except asyncio.TimeoutError:
                            pass  # Cognitive inference timed out - continue
                        except Exception as e:
                            print(f"[Cognitive] Error: {e}", file=sys.stderr, flush=True)

            # ==================== ENHANCED LEARNING INTEGRATION ====================

            # 2b-i. Adaptive Prediction: Learn from what just happened
            if adaptive_model:
                try:
                    observations = {
                        "light": readings.light_lux,
                        "ambient_temp": readings.ambient_temp_c,
                        "humidity": readings.humidity_pct,
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                    }
                    # Remove None values
                    observations = {k: v for k, v in observations.items() if v is not None}
                    adaptive_model.observe(
                        observations,
                        current_light=readings.light_lux,
                        current_temp=readings.ambient_temp_c
                    )
                except Exception as e:
                    print(f"[Learning] Adaptive prediction error: {e}", file=sys.stderr, flush=True)

            # 2b-ii. Update Self-Model with observations
            if self_model:
                try:
                    # Track surprise for self-beliefs
                    self_model.observe_surprise(pred_error.surprise, pred_error.surprise_sources)

                    # Track stability changes
                    if last_state_for_action:
                        prev_stability = last_state_for_action.get("stability", anima.stability)
                        self_model.observe_stability_change(prev_stability, anima.stability, UPDATE_INTERVAL)

                    # Track correlations
                    sensor_vals = {
                        "ambient_temp": readings.ambient_temp_c,
                        "light": readings.light_lux,
                    }
                    anima_vals = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                    }
                    self_model.observe_correlation(sensor_vals, anima_vals)

                    # Track LED-lux proprioception (own outputs affecting inputs)
                    self_model.observe_led_lux(readings.led_brightness, readings.light_lux)

                    # Track time patterns
                    hour = datetime.now().hour
                    self_model.observe_time_pattern(hour, anima.warmth, anima.clarity)
                except Exception as e:
                    print(f"[Learning] Self-model error: {e}", file=sys.stderr, flush=True)

            # 2b-iii. Update Preferences from experience
            if preferences:
                try:
                    current_state = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                    }
                    preferences.record_state(current_state)

                    # Record events that shape preferences
                    if pred_error.surprise > 0.4:
                        # High surprise is mildly negative (prefer predictability)
                        preferences.record_event("disruption", -0.2, current_state)
                    elif pred_error.surprise < 0.1 and anima.stability > 0.6:
                        # Low surprise + high stability is positive
                        preferences.record_event("calm", 0.3, current_state)
                except Exception as e:
                    print(f"[Learning] Preference error: {e}", file=sys.stderr, flush=True)

            # 2b-iv. Memory Retrieval: Let past inform present
            relevant_memories = []
            if memory_retriever and should_reflect:
                try:
                    # Retrieve memories relevant to current surprise
                    relevant_memories = loop.run_until_complete(
                        asyncio.wait_for(
                            retrieve_relevant_memories(
                                surprise_sources=pred_error.surprise_sources,
                                warmth=anima.warmth,
                                clarity=anima.clarity,
                                stability=anima.stability,
                                limit=2
                            ),
                            timeout=2.0
                        )
                    )
                    if relevant_memories:
                        memory_context = memory_retriever.format_for_context(relevant_memories)
                        print(f"[Memory] Retrieved: {len(relevant_memories)} relevant memories", file=sys.stderr, flush=True)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"[Learning] Memory retrieval error: {e}", file=sys.stderr, flush=True)

            # 2b-v. Action Selection: Choose what to do based on state and preferences
            selected_action = None
            if action_selector and preferences:
                try:
                    current_state = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                        "last_surprise": pred_error.surprise,
                    }

                    selected_action = action_selector.select_action(
                        current_state,
                        preferences=preferences,
                        surprise_level=pred_error.surprise,
                        surprise_sources=pred_error.surprise_sources,
                        can_speak=voice is not None,
                    )

                    # Execute action effects
                    if selected_action.action_type == ActionType.FOCUS_ATTENTION:
                        sensor = selected_action.parameters.get("sensor")
                        action_selector.set_attention_focus(sensor)
                        print(f"[Agency] Focusing attention on: {sensor}", file=sys.stderr, flush=True)

                    elif selected_action.action_type == ActionType.ADJUST_SENSITIVITY:
                        direction = selected_action.parameters.get("direction", "increase")
                        action_selector.adjust_sensitivity(direction)
                        print(f"[Agency] Sensitivity {direction}d", file=sys.stderr, flush=True)

                    elif selected_action.action_type == ActionType.ASK_QUESTION:
                        # Generate question from metacognition (existing functionality)
                        pass  # Question generation already happens via metacognition

                    # Record state for action outcome learning
                    satisfaction_before = preferences.get_overall_satisfaction(current_state)
                    last_state_for_action = {**current_state, "satisfaction": satisfaction_before}
                    last_action = selected_action

                except Exception as e:
                    print(f"[Agency] Action selection error: {e}", file=sys.stderr, flush=True)

            # 2b-vi. Record action outcomes (from previous iteration)
            if action_selector and last_action and last_state_for_action and preferences:
                try:
                    current_state = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                    }
                    satisfaction_after = preferences.get_overall_satisfaction(current_state)

                    action_selector.record_outcome(
                        last_action,
                        last_state_for_action,
                        current_state,
                        last_state_for_action.get("satisfaction", 0.5),
                        satisfaction_after,
                        pred_error.surprise,
                    )
                except Exception as e:
                    print(f"[Agency] Outcome recording error: {e}", file=sys.stderr, flush=True)

            # 2b-vii. Exploration check
            if exploration_mgr:
                try:
                    should_explore, explore_reason = exploration_mgr.should_explore(
                        {"stability": anima.stability, "clarity": anima.clarity},
                        pred_error.surprise
                    )
                    if should_explore:
                        exploration_mgr.record_novelty(pred_error.surprise, explore_reason)
                        print(f"[Agency] Exploration triggered: {explore_reason}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[Agency] Exploration error: {e}", file=sys.stderr, flush=True)

            # ==================== END ENHANCED LEARNING ====================

            # 2c. Update Voice with anima state (influences when/how Lumen speaks)
            if voice:
                try:
                    feeling = anima.feeling()
                    voice.update_state(
                        warmth=anima.warmth,
                        clarity=anima.clarity,
                        stability=anima.stability,
                        presence=anima.presence,
                        mood=feeling.get("mood", "neutral")
                    )
                    voice.update_environment(
                        temperature=readings.ambient_temp_c or readings.cpu_temp_c or 22.0,
                        humidity=readings.humidity_pct or 50.0,
                        light_level=readings.light_lux or 500.0
                    )
                except Exception as e:
                    print(f"[StableCreature] Voice update error: {e}", file=sys.stderr, flush=True)

            # 3. Governance Check-in (if bridge available) - do BEFORE shared memory write
            # Rate limited to every GOVERNANCE_INTERVAL seconds to avoid overwhelming server
            # First check-in always happens (to sync identity), then rate limited
            current_time = time.time()
            should_check_governance = first_check_in or (current_time - last_governance_time >= GOVERNANCE_INTERVAL)

            if bridge and should_check_governance:
                try:
                    # Add timeout to prevent freezing if UNITARES is slow
                    is_available = loop.run_until_complete(
                        asyncio.wait_for(bridge.check_availability(), timeout=2.0)
                    )
                    if is_available or bridge._url is None: # local fallback works even if url is None
                        decision = loop.run_until_complete(
                            asyncio.wait_for(
                                bridge.check_in(anima, readings, identity=identity, is_first_check_in=first_check_in),
                                timeout=2.0
                            )
                        )
                        last_decision = decision
                        last_governance_time = current_time
                        first_check_in = False  # Only sync identity metadata once
                        # Record interaction if governance indicates human involvement
                        if activity_manager and decision and decision.get("action") == "wait_for_input":
                            activity_manager.record_interaction()
                except asyncio.TimeoutError:
                    # Governance timeout is normal if network is slow - continue silently
                    last_governance_time = current_time  # Still count as a check to avoid retry spam
                except asyncio.CancelledError:
                    # Task cancelled - don't propagate, just continue
                    pass
                except Exception as e:
                    # Log but never crash - governance is optional
                    last_governance_time = current_time  # Avoid retry spam on errors
                    if "Connection refused" not in str(e) and "Cannot connect" not in str(e):
                        print(f"[StableCreature] Governance error (non-fatal): {e}", file=sys.stderr, flush=True)

            # 3b. Write to Shared Memory (Broker) - includes governance and metacognition
            shm_data = {
                "timestamp": datetime.now().isoformat(),
                "readings": readings.to_dict(),
                "anima": anima.to_dict(),
                "eisv": eisv.to_dict(),
                "identity": {
                    "creature_id": identity.creature_id,
                    "name": identity.name,
                    "awakenings": identity.total_awakenings
                },
                "metacognition": {
                    "surprise": pred_error.surprise,
                    "surprise_sources": pred_error.surprise_sources,
                    "cumulative_surprise": metacog._cumulative_surprise,
                    "prediction_confidence": prediction.confidence,
                }
            }
            if last_decision:
                shm_data["governance"] = last_decision

            # Add activity state if available
            if activity_state:
                shm_data["activity"] = {
                    "level": activity_state.level.value,
                    "brightness_multiplier": activity_state.brightness_multiplier,
                    "reason": activity_state.reason,
                }

            # Add enhanced learning state if available
            if ENHANCED_LEARNING_AVAILABLE:
                learning_state = {}
                if preferences:
                    try:
                        learning_state["preferences"] = {
                            "satisfaction": preferences.get_overall_satisfaction({
                                "warmth": anima.warmth, "clarity": anima.clarity,
                                "stability": anima.stability, "presence": anima.presence
                            }),
                            "most_unsatisfied": preferences.get_most_unsatisfied({
                                "warmth": anima.warmth, "clarity": anima.clarity,
                                "stability": anima.stability, "presence": anima.presence
                            }),
                        }
                    except:
                        pass
                if self_model:
                    try:
                        learning_state["self_beliefs"] = self_model.get_belief_summary()
                    except:
                        pass
                if action_selector:
                    try:
                        learning_state["agency"] = action_selector.get_action_stats()
                    except:
                        pass
                if adaptive_model:
                    try:
                        learning_state["prediction_accuracy"] = adaptive_model.get_accuracy_stats()
                    except:
                        pass
                if learning_state:
                    shm_data["learning"] = learning_state

            shm_client.write(shm_data)

            # 4. Render Face
            face_state = derive_face_state(anima)

            # Modify face based on activity state (sleeping/drowsy)
            if activity_state and activity_state.level == ActivityLevel.RESTING:
                # Eyes closed when resting
                face_state.eyes = EyeState.CLOSED
                face_state.eye_openness = 0.0
            elif activity_state and activity_state.level == ActivityLevel.DROWSY:
                # Droopy eyes when drowsy
                face_state.eyes = EyeState.DROOPY
                face_state.eye_openness = 0.4

            ascii_face = face_to_ascii(face_state)
            
            # Clear screen (terminal) - use ANSI codes to prevent flicker
            # \033[2J = clear screen, \033[H = move cursor to top-left
            print("\033[2J\033[H", end="")
            
            # Print identity and mood
            print(f"Name: {identity.name or 'Anima'} | Mood: {anima.feeling()['mood']}")
            print(f"W: {anima.warmth:.2f} | C: {anima.clarity:.2f} | S: {anima.stability:.2f} | P: {anima.presence:.2f}")
            
            # Print face
            print(ascii_face)
            
            # Print governance if available
            if last_decision:
                action = last_decision.get("action", "UNKNOWN")
                reason = last_decision.get("reason", "")
                print(f"Governance: {action.upper()} - {reason}")
            
            # Print metacognition if surprise is notable
            if pred_error.surprise > 0.1:
                sources = ", ".join(pred_error.surprise_sources) if pred_error.surprise_sources else "general"
                print(f"Surprise: {pred_error.surprise:.0%} ({sources})")
            
            # DB writes removed: server owns identity DB (Option 1 - no contention).
            # Broker only writes to shared memory; server does record_state/heartbeat.

            # Periodic learning save: Save learning state every 5 minutes to survive crashes
            if ENHANCED_LEARNING_AVAILABLE and time.time() - last_learning_save > 300:
                try:
                    if adaptive_model:
                        adaptive_model._save_patterns()
                    if preferences:
                        preferences._save()
                    if self_model:
                        self_model.save()
                    last_learning_save = time.time()
                except Exception:
                    pass  # Non-fatal

            time.sleep(UPDATE_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean shutdown
        print("[StableCreature] Shutting down...")

        # Save enhanced learning state
        if ENHANCED_LEARNING_AVAILABLE:
            try:
                if adaptive_model:
                    adaptive_model._save_patterns()
                    print("[StableCreature] Saved adaptive prediction patterns")
                if preferences:
                    preferences._save()
                    print("[StableCreature] Saved preferences")
                if self_model:
                    self_model.save()
                    print("[StableCreature] Saved self-model")
            except Exception as e:
                print(f"[StableCreature] Error saving learning state: {e}")

        if voice:
            try:
                voice.stop()
            except Exception:
                pass

        # Close UNITARES bridge session (connection pooling cleanup)
        if bridge:
            try:
                loop.run_until_complete(bridge.close())
            except Exception:
                pass

        loop.close()
        if store:
            store.sleep()
            store.close()
        shm_client.clear()  # Clean up shared memory
        print("[StableCreature] Stopped.")

def main():
    """Entry point for pyproject.toml scripts."""
    run_creature()


if __name__ == "__main__":
    main()
