"""Small asset-free presentation helpers shared by monitoring tiles."""

import html


def trend(values: list[float], label: str) -> str:
    maximum = max(values, default=0) or 1
    points = " ".join(
        f"{index * 300 / max(1, len(values) - 1):.1f},{60 - value / maximum * 56:.1f}"
        for index, value in enumerate(values)
    )
    last_x = 300 if len(values) > 1 else 0
    last_y = 60 - (values[-1] if values else 0) / maximum * 56
    return (
        '<svg class="monitoring-trend" viewBox="0 0 300 64" role="img" '
        f'aria-label="{html.escape(label, quote=True)}"><title>{html.escape(label)}</title>'
        f'<polyline points="{points}" fill="none" stroke="currentColor" stroke-width="2" />'
        f'<circle cx="{last_x}" cy="{last_y:.1f}" r="2" fill="currentColor" />'
        '</svg>'
    )
