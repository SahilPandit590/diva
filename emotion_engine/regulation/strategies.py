"""
Regulation Strategy Definitions for Diva Emotion Engine v1.0.0.
Implements the 4 formal regulation strategies from Part 1.9.
"""

from typing import Dict, Tuple
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.types.enums import RegulationStrategyType


class RegulationStrategyDefinition(BaseModel):
    """Specification of a psychological emotional regulation strategy."""
    model_config = ConfigDict(frozen=True)

    strategy_type: RegulationStrategyType
    name: str
    damping_factor: float = Field(ge=0.0, le=1.0)
    cognitive_effort_cost: float = Field(ge=0.0, le=1.0)
    applicable_categories: Tuple[str, ...]
    description: str


REGULATION_STRATEGIES: Dict[RegulationStrategyType, RegulationStrategyDefinition] = {
    RegulationStrategyType.COGNITIVE_REAPPRAISAL: RegulationStrategyDefinition(
        strategy_type=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
        name="Cognitive Reappraisal",
        damping_factor=0.35,  # Modulates intensity downward by 35%
        cognitive_effort_cost=0.40,
        applicable_categories=("Anger", "Distress", "Frustration", "Fear", "Anxiety", "Sadness", "Jealousy", "Resentment"),
        description="Generates an alternative contextual reframing with Thought Engine, diminishing acute distress.",
    ),
    RegulationStrategyType.ATTENTIONAL_DEPLOYMENT: RegulationStrategyDefinition(
        strategy_type=RegulationStrategyType.ATTENTIONAL_DEPLOYMENT,
        name="Attentional Deployment",
        damping_factor=0.25,  # Modulates intensity downward by 25%
        cognitive_effort_cost=0.20,
        applicable_categories=("Anger", "Distress", "Fear", "Frustration", "Envy", "Embarrassment"),
        description="Shifts focal attention away from the distressing stimulus toward neutral or constructive anchors.",
    ),
    RegulationStrategyType.PACING_HEURISTIC: RegulationStrategyDefinition(
        strategy_type=RegulationStrategyType.PACING_HEURISTIC,
        name="Pacing Heuristic",
        damping_factor=0.20,  # Modulates intensity downward by 20%
        cognitive_effort_cost=0.15,
        applicable_categories=("Distress", "Anger", "Surprise", "Anxiety", "Excitement"),
        description="Executes internal pacing and breathing heuristics via Energy Regulation, stabilizing arousal.",
    ),
    RegulationStrategyType.EXPRESSIVE_MODULATION: RegulationStrategyDefinition(
        strategy_type=RegulationStrategyType.EXPRESSIVE_MODULATION,
        name="Expressive Modulation",
        damping_factor=0.10,  # Modulates external intensity by 10%
        cognitive_effort_cost=0.10,
        applicable_categories=("Anger", "Frustration", "Excitement", "Disgust", "Embarrassment"),
        description="Modulates external delivery cues while maintaining complete internal affective fidelity.",
    ),
}
