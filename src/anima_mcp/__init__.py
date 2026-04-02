"""
Anima MCP - A persistent creature with grounded self-sense

One creature. One identity. Real sensors. Real presence.

Anima: the animating principle, the felt sense of being alive.
"""

__version__ = "1.0.0"

# Core exports
from .anima import Anima as Anima, sense_self as sense_self
from .sensors import SensorReadings as SensorReadings, SensorBackend as SensorBackend, get_sensors as get_sensors
from .config import (
    NervousSystemCalibration as NervousSystemCalibration,
    DisplayConfig as DisplayConfig,
    AnimaConfig as AnimaConfig,
    ConfigManager as ConfigManager,
    get_calibration as get_calibration,
    get_display_config as get_display_config,
    get_config_manager as get_config_manager,
)
from .learning import AdaptiveLearner as AdaptiveLearner, get_learner as get_learner
from .workflow_orchestrator import (
    UnifiedWorkflowOrchestrator as UnifiedWorkflowOrchestrator,
    get_orchestrator as get_orchestrator,
    WorkflowStep as WorkflowStep,
    WorkflowStatus as WorkflowStatus,
)
from .shared_memory import SharedMemoryClient as SharedMemoryClient

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
    from .eisv_mapper import (
        EISVMetrics as EISVMetrics,
        anima_to_eisv as anima_to_eisv,
        compute_eisv_from_readings as compute_eisv_from_readings,
    )
    from .unitares_bridge import UnitaresBridge as UnitaresBridge, check_governance as check_governance
    from .next_steps_advocate import NextStepsAdvocate as NextStepsAdvocate, get_advocate as get_advocate
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
        from .next_steps_advocate import (
            NextStepsAdvocate as NextStepsAdvocate,
            get_advocate as get_advocate,
        )
        __all__ = _BASE_ALL + [
            "NextStepsAdvocate",
            "get_advocate",
        ]
    except ImportError:
        __all__ = list(_BASE_ALL)
