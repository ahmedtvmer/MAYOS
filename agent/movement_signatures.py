"""Shared Movement signature matching for generation and coverage reporting."""

from agent.program_blueprints import SlotSpec


def matches_movement_signature(
    primary_action: object,
    primary_muscle: object,
    spec: SlotSpec,
) -> bool:
    """Return whether both curated fields are allowed by the slot signature."""
    return (
        bool(primary_action)
        and bool(primary_muscle)
        and primary_action in spec.primary_actions
        and primary_muscle in spec.primary_muscles
    )
