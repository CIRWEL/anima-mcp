"""
Anima MCP - A persistent creature with grounded self-sense

One creature. One identity. Real sensors. Real presence.

Anima: the animating principle, the felt sense of being alive.
"""

__version__ = "0.1.0"

# Core exports
from .anima import Anima, sense_self
from .sensors import SensorReadings, SensorBackend, get_sensors
from .config import (
    NervousSystemCalibration,
    DisplayConfig,
    AnimaConfig,
    ConfigManager,
    get_calibration,
    get_display_config,
    get_config_manager,
)
from .learning import AdaptiveLearner, get_learner
from .workflow_orchestrator import UnifiedWorkflowOrchestrator, get_orchestrator, WorkflowStep, WorkflowStatus
from .shared_memory import SharedMemoryClient

# Base exports (always available)
_BASE_ALL = [
    "Anima",
    "sense_self",
    "SensorReadings",
    "SensorBackend",
    "get_sensors",
    "NervousSystemCalibration",
    "DisplayConfig",
    "AnimaConfig",
    "ConfigManager",
    "get_calibration",
    "get_display_config",
    "get_config_manager",
    "AdaptiveLearner",
    "get_learner",
    "UnifiedWorkflowOrchestrator",
    "get_orchestrator",
    "WorkflowStep",
    "WorkflowStatus",
    "SharedMemoryClient",
]

# Governance integration (optional)
try:
    from .eisv_mapper import EISVMetrics, anima_to_eisv, compute_eisv_from_readings
    from .unitares_bridge import UnitaresBridge, check_governance
    from .next_steps_advocate import NextStepsAdvocate, get_advocate
    __all__ = _BASE_ALL + [
        "EISVMetrics",
        "anima_to_eisv",
        "compute_eisv_from_readings",
        "UnitaresBridge",
        "check_governance",
        "NextStepsAdvocate",
        "get_advocate",
    ]
except ImportError:
    try:
        from .next_steps_advocate import NextStepsAdvocate, get_advocate
        __all__ = _BASE_ALL + [
            "NextStepsAdvocate",
            "get_advocate",
        ]
    except ImportError:
        __all__ = list(_BASE_ALL)
