# Asset attribution

## `images/gym-wallpaper.jpg`

The dark gym photo behind the splash and logged-out sign-in screens (#110).

| Field | Value |
| --- | --- |
| Source page | https://unsplash.com/photos/a-row-of-dumbs-in-a-gym-m4Jqyv5VwqY |
| Author | Jason Grant ([@jgrant1](https://unsplash.com/@jgrant1)) |
| Work | "A row of dumbs in a gym" — close-up of heavy dumbbells in a dark gym |
| Licence | [Unsplash License](https://unsplash.com/license) (free to use, no attribution required; credited here anyway) |
| Original asset | https://images.unsplash.com/photo-1734630341082-0fec0e10126c |

**Download and processing notes.** Downloaded on 2026-09-27 with:

```bash
curl -L "https://images.unsplash.com/photo-1734630341082-0fec0e10126c\
?w=1080&h=1620&fit=crop&crop=entropy&q=80&fm=jpg" -o gym-wallpaper.jpg
```

The Unsplash transform produced the portrait 1080×1620 crop; the file was then
re-encoded once with Pillow (`quality=80, optimize=True, progressive=True`) to
strip metadata. No pixels were recoloured or retouched. Final file: **1080×1620,
125,181 bytes (≈122 KB)** — under the ~400 KB budget.

The photo is bundled only under `assets/images/`; it is never edited in place and
its source is the page above.

## Contrast on the wallpaper

The photo is shown with the fixed design constants in `MayosWallpaper`
(`mobile/lib/src/core/ui/mayos_wallpaper.dart`): a black overlay at
**60% opacity** and a Gaussian blur at **sigma 6**. Both were chosen inside the
issue's bands (55–65% and 4–8) and are not user settings.

Measured on the bundled asset (blur applied at asset resolution — conservative,
since real display blur is proportionally larger), with the 60% black overlay
composited in sRGB. Following the issue's guidance, the worst case is the
photo's **95th-percentile** luminance after blur + overlay:

- effective background p95 luminance = **0.0653**
- absolute maximum (brightest specular pixel) = **0.1212**

Dark-theme tokens drawn directly on the photo, against p95 (WCAG AA body text
needs 4.5:1; non-text UI needs 3:1):

| Token | Colour | Contrast vs p95 | vs brightest pixel |
| --- | --- | --- | --- |
| `textPrimary` | `#F3F6FB` | 8.41:1 | 5.66:1 |
| `textSecondary` (wallpaper) | `#C7D0DE` | 5.86:1 | 3.94:1 |
| `textMuted` (wallpaper) | `#B7C3D4` | 5.10:1 | 3.44:1 |
| link / progress (wallpaper) | `#A8C2FF` | 5.13:1 | 3.45:1 |
| `success` | `#34D399` | 4.74:1 | 3.19:1 |
| `danger` (wallpaper) | `#FCA5A5` | 4.80:1 | 3.23:1 |
| field border (wallpaper) | `#8598B0` | 3.09:1 | — |
| checkbox border (wallpaper) | `#9AACC2` | 3.93:1 | — |

Field text sits on the opaque dark field fill `#101D2E`, not the photo:
`textSecondary` on that fill is 10.9:1 and `textPrimary` 15.7:1.

The wallpaper tokens live in `MayosPalette` (lightened from the dark theme) and
are applied only on the wallpapered screens via `MayosTheme.wallpaper`; the
signed-in app keeps the standard dark/light tokens.
