"""
Workflow Templates - Common workflow patterns for agents.

Makes the workflow orchestrator more accessible by providing pre-defined
workflow templates for common tasks.

Usage:
    templates = WorkflowTemplates(orchestrator)
    result = await templates.run("health_check")
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .workflow_orchestrator import UnifiedWorkflowOrchestrator, WorkflowStep, WorkflowResult


@dataclass
class WorkflowTemplate:
    """A reusable workflow template."""
    name: str
    description: str
    steps: List[WorkflowStep]
    parallel: bool = False
    category: str = "general"


class WorkflowTemplates:
    """
    Collection of workflow templates for common tasks.
    
    Makes workflows more accessible - agents can use pre-defined patterns
    instead of building workflows from scratch.
    """
    
    def __init__(self, orchestrator: UnifiedWorkflowOrchestrator):
        """
        Initialize templates with orchestrator.
        
        Args:
            orchestrator: Workflow orchestrator instance
        """
        self._orchestrator = orchestrator
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._register_templates()
    
    def _register_templates(self):
        """Register all workflow templates."""
        
        # Health Check - Quick system health overview
        self._templates["health_check"] = WorkflowTemplate(
            name="health_check",
            description="Quick health check - Lumen's state, sensors, and basic diagnostics",
            steps=[
                WorkflowStep(
                    name="get_state",
                    server="anima",
                    tool="get_state",
                    arguments={}
                ),
                WorkflowStep(
                    name="read_sensors",
                    server="anima",
                    tool="read_sensors",
                    arguments={}
                ),
            ],
            parallel=True,
            category="health"
        )
        
        # Full System Check - Comprehensive system status
        self._templates["full_system_check"] = WorkflowTemplate(
            name="full_system_check",
            description="Comprehensive system check - state, sensors, identity, and governance",
            steps=[
                WorkflowStep(
                    name="get_state",
                    server="anima",
                    tool="get_state",
                    arguments={}
                ),
                WorkflowStep(
                    name="get_identity",
                    server="anima",
                    tool="get_identity",
                    arguments={}
                ),
                WorkflowStep(
                    name="check_governance",
                    server="unitares",
                    tool="check_governance",
                    arguments={},
                    depends_on=["get_state"]  # Needs state for governance
                ),
            ],
            parallel=False,  # Sequential - governance depends on state
            category="health"
        )
        
        # Learning Check - Check learning system status
        self._templates["learning_check"] = WorkflowTemplate(
            name="learning_check",
            description="Check learning system - observations, calibration, and learning readiness",
            steps=[
                WorkflowStep(
                    name="get_state",
                    server="anima",
                    tool="get_state",
                    arguments={}
                ),
                WorkflowStep(
                    name="get_calibration",
                    server="anima",
                    tool="get_calibration",
                    arguments={}
                ),
            ],
            parallel=True,
            category="learning"
        )
        
        # Governance Check - Just governance decision
        self._templates["governance_check"] = WorkflowTemplate(
            name="governance_check",
            description="Check governance decision - get UNITARES decision for current state",
            steps=[
                WorkflowStep(
                    name="get_state",
                    server="anima",
                    tool="get_state",
                    arguments={}
                ),
                WorkflowStep(
                    name="check_governance",
                    server="unitares",
                    tool="check_governance",
                    arguments={},
                    depends_on=["get_state"]
                ),
            ],
            parallel=False,
            category="governance"
        )
        
        # Identity Check - Get Lumen's identity and history
        self._templates["identity_check"] = WorkflowTemplate(
            name="identity_check",
            description="Get Lumen's identity - name, age, awakenings, existence",
            steps=[
                WorkflowStep(
                    name="get_identity",
                    server="anima",
                    tool="get_identity",
                    arguments={}
                ),
            ],
            parallel=False,
            category="identity"
        )
        
        # Sensor Deep Dive - Detailed sensor analysis
        self._templates["sensor_analysis"] = WorkflowTemplate(
            name="sensor_analysis",
            description="Detailed sensor analysis - readings, calibration, comfort zones",
            steps=[
                WorkflowStep(
                    name="read_sensors",
                    server="anima",
                    tool="read_sensors",
                    arguments={}
                ),
                WorkflowStep(
                    name="get_calibration",
                    server="anima",
                    tool="get_calibration",
                    arguments={}
                ),
            ],
            parallel=True,
            category="sensors"
        )
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all available workflow templates.
        
        Returns:
            List of template metadata
        """
        return [
            {
                "name": template.name,
                "description": template.description,
                "category": template.category,
                "steps": len(template.steps),
                "parallel": template.parallel,
            }
            for template in self._templates.values()
        ]
    
    def get_template(self, name: str) -> Optional[WorkflowTemplate]:
        """
        Get a workflow template by name.
        
        Args:
            name: Template name
        
        Returns:
            WorkflowTemplate or None if not found
        """
        return self._templates.get(name)
    
    async def run(self, template_name: str, **kwargs) -> WorkflowResult:
        """
        Run a workflow template.
        
        Args:
            template_name: Name of template to run
            **kwargs: Optional overrides for template arguments
        
        Returns:
            WorkflowResult with execution status and results
        """
        template = self._templates.get(template_name)
        if not template:
            # Return error result
            from .workflow_orchestrator import WorkflowStatus
            return WorkflowResult(
                status=WorkflowStatus.FAILED,
                steps={},
                errors={"template": f"Unknown template: {template_name}"},
                summary=f"Template '{template_name}' not found"
            )
        
        # Apply any argument overrides
        steps = []
        for step in template.steps:
            # Create new step with overridden arguments if provided
            step_args = step.arguments.copy()
            if template_name in kwargs:
                step_args.update(kwargs[template_name])
            steps.append(WorkflowStep(
                name=step.name,
                server=step.server,
                tool=step.tool,
                arguments=step_args,
                depends_on=step.depends_on
            ))
        
        # Execute workflow
        return await self._orchestrator.execute_workflow(
            steps=steps,
            parallel=template.parallel
        )
    
    def get_template_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a template.
        
        Args:
            name: Template name
        
        Returns:
            Template info dict or None
        """
        template = self._templates.get(name)
        if not template:
            return None
        
        return {
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "parallel": template.parallel,
            "steps": [
                {
                    "name": step.name,
                    "server": step.server,
                    "tool": step.tool,
                    "arguments": step.arguments,
                    "depends_on": step.depends_on,
                }
                for step in template.steps
            ],
        }
