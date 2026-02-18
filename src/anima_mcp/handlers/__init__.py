"""MCP Tool Handlers — organized by domain.

Handlers are extracted from the monolithic server.py into focused modules.
Each module groups handlers by their functional area.
"""

from .system_ops import (
    handle_git_pull,
    handle_system_service,
    handle_fix_ssh_port,
    handle_deploy_from_github,
    handle_setup_tailscale,
    handle_system_power,
)

from .state_queries import (
    handle_get_state,
    handle_get_identity,
    handle_read_sensors,
    handle_get_health,
    handle_get_calibration,
)

from .knowledge import (
    handle_get_self_knowledge,
    handle_get_growth,
    handle_get_qa_insights,
    handle_get_trajectory,
    handle_get_eisv_trajectory_state,
)

from .display_ops import (
    handle_capture_screen,
    handle_show_face,
    handle_diagnostics,
    handle_manage_display,
)

from .communication import (
    handle_lumen_qa,
    handle_post_message,
    handle_say,
    handle_configure_voice,
    handle_primitive_feedback,
)

from .workflows import (
    handle_unified_workflow,
    handle_next_steps,
    handle_set_calibration,
    handle_get_lumen_context,
    handle_learning_visualization,
)

__all__ = [
    # System operations (zero global state dependencies)
    "handle_git_pull",
    "handle_system_service",
    "handle_fix_ssh_port",
    "handle_deploy_from_github",
    "handle_setup_tailscale",
    "handle_system_power",
    # State queries (read-only)
    "handle_get_state",
    "handle_get_identity",
    "handle_read_sensors",
    "handle_get_health",
    "handle_get_calibration",
    # Knowledge (read-only)
    "handle_get_self_knowledge",
    "handle_get_growth",
    "handle_get_qa_insights",
    "handle_get_trajectory",
    "handle_get_eisv_trajectory_state",
    # Display operations
    "handle_capture_screen",
    "handle_show_face",
    "handle_diagnostics",
    "handle_manage_display",
    # Communication
    "handle_lumen_qa",
    "handle_post_message",
    "handle_say",
    "handle_configure_voice",
    "handle_primitive_feedback",
    # Workflows
    "handle_unified_workflow",
    "handle_next_steps",
    "handle_set_calibration",
    "handle_get_lumen_context",
    "handle_learning_visualization",
]
