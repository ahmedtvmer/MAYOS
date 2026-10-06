"""SQL ranking shared by Exercise library replacement candidate searches."""


def replacement_rank_sql() -> str:
    """Return the replacement's action-and-muscle ranking groups."""
    return """CASE
        WHEN replacement_cf.primary_action IS NOT NULL
            AND replacement_cf.primary_muscle IS NOT NULL
            AND cf.primary_action = replacement_cf.primary_action
            AND cf.primary_muscle = replacement_cf.primary_muscle THEN 0
        WHEN replacement_cf.primary_action IS NOT NULL
            AND cf.primary_action = replacement_cf.primary_action THEN 1
        WHEN replacement_cf.primary_muscle IS NOT NULL
            AND cf.primary_muscle = replacement_cf.primary_muscle THEN 2
        ELSE 3
    END"""
