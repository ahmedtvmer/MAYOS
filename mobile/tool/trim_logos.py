#!/usr/bin/env python3
"""Generate trimmed MAYOS brand assets from the supplied originals.

The originals in ``assets/mayos-logo-{white,blue,black}.png`` are never
modified. This script derives, deterministically:

  * ``mobile/assets/brand/mayos-lockup-<variant>.png`` — the mark + wordmark
    lockup cropped to its content bounding box (plus a small transparent pad).
    Sparse, low-alpha regions separated from the lockup (e.g. the faint
    artifacts near the black wordmark) are excluded.
  * ``mobile/assets/brand/mayos-mark-<variant>.png`` — the mark only, split
    from the wordmark at the largest gap inside the lockup.

Run from anywhere:

    python3 mobile/tool/trim_logos.py

Requires Pillow and numpy. Re-running produces identical bytes for identical
inputs (no randomness, no resampling).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]  # repo root
SRC = ROOT / "assets"
OUT = ROOT / "mobile" / "assets" / "brand"

VARIANTS = ("white", "blue", "black")

# Pixels at or above this alpha count as ink. Kept above the faint artifact
# range so isolated low-alpha marks do not define the content box.
ALPHA_THRESHOLD = 32

# Row runs closer than this are merged (only tiny antialias gaps inside one
# element merge; the mark/wordmark gap and the black artifact gap are larger).
MERGE_GAP = 6

# A merged run is dropped as an artifact when its ink is below both bounds.
MIN_RUN_INK_ABSOLUTE = 400
MIN_RUN_INK_FRACTION = 0.02  # of the largest merged run

# Transparent padding kept around each crop, clamped to the image.
PAD = 12


def _row_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for row in range(mask.shape[0]):
        has_ink = bool(mask[row].any())
        if has_ink and start is None:
            start = row
        elif not has_ink and start is not None:
            runs.append((start, row - 1))
            start = None
    if start is not None:
        runs.append((start, mask.shape[0] - 1))
    return runs


def _merge(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] - 1 <= gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _column_span(mask: np.ndarray, top: int, bottom: int) -> tuple[int, int]:
    columns = np.where(mask[top : bottom + 1].sum(axis=0) > 0)[0]
    return int(columns.min()), int(columns.max())


def _clamp_box(
    left: int, top: int, right: int, bottom: int, width: int, height: int
) -> tuple[int, int, int, int]:
    return (
        max(0, left),
        max(0, top),
        min(width, right),
        min(height, bottom),
    )


def process(variant: str) -> None:
    source = SRC / f"mayos-logo-{variant}.png"
    image = Image.open(source).convert("RGBA")
    width, height = image.size
    mask = np.array(image)[:, :, 3] >= ALPHA_THRESHOLD

    merged = _merge(_row_runs(mask), MERGE_GAP)
    ink = [int(mask[start : end + 1].sum()) for start, end in merged]
    largest = max(ink)
    kept = [
        run
        for run, amount in zip(merged, ink)
        if amount >= max(MIN_RUN_INK_ABSOLUTE, MIN_RUN_INK_FRACTION * largest)
    ]

    lock_top, lock_bottom = kept[0][0], kept[-1][1]
    lock_left, lock_right = _column_span(mask, lock_top, lock_bottom)
    lock_box = _clamp_box(
        lock_left - PAD, lock_top - PAD, lock_right + 1 + PAD, lock_bottom + 1 + PAD,
        width, height,
    )

    # Split mark from wordmark at the largest gap between kept runs. With a
    # single kept run (no wordmark), the mark is the whole lockup.
    if len(kept) >= 2:
        gaps = [
            (kept[i + 1][0] - kept[i][1] - 1, kept[i][1], kept[i + 1][0])
            for i in range(len(kept) - 1)
        ]
        _, mark_bottom, wordmark_top = max(gaps)
    else:
        mark_bottom, wordmark_top = lock_bottom, height
    mark_left, mark_right = _column_span(mask, lock_top, mark_bottom)
    # Never let the mark's padding bleed into the wordmark.
    mark_bottom_padded = min(mark_bottom + 1 + PAD, wordmark_top)
    mark_box = _clamp_box(
        mark_left - PAD, lock_top - PAD, mark_right + 1 + PAD, mark_bottom_padded,
        width, height,
    )

    lockup_path = OUT / f"mayos-lockup-{variant}.png"
    mark_path = OUT / f"mayos-mark-{variant}.png"
    image.crop(lock_box).save(lockup_path)
    image.crop(mark_box).save(mark_path)

    print(f"{variant}:")
    print(f"  source        {source.relative_to(ROOT)} {width}x{height}")
    print(f"  lockup bbox   {lock_box}  -> {lockup_path.name}")
    print(f"  mark bbox     {mark_box}  -> {mark_path.name}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        process(variant)


if __name__ == "__main__":
    main()
