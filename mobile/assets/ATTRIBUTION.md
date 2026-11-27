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

**Black and white (#886).** On 2026-11-27 the file was converted to greyscale
with Pillow (`convert("L")`, contrast ×1.1) and re-saved with the same settings
(`quality=80, optimize=True, progressive=True`), so its cold teal grade no
longer clashes with the red-on-charcoal colours. The Unsplash License allows
modification. Same crop and size; `web/mayos-loading-wallpaper.jpg` got the
same conversion.

The photo is bundled only under `assets/images/`; its source is the page above.

## Contrast on the wallpaper

The photo is shown with the fixed design constants in `MayosWallpaper`
(`mobile/lib/src/core/ui/mayos_wallpaper.dart`): a black overlay at
**60% opacity** and a Gaussian blur at **sigma 6**. Both were chosen inside the
issue's bands (55–65% and 4–8) and are not user settings.

Measured on the bundled asset (blur applied at asset resolution — conservative,
since real display blur is proportionally larger), with the 60% black overlay
composited in sRGB. Following the issue's guidance, the worst case is the
photo's **95th-percentile** luminance after blur + overlay:

- effective background p95 luminance = **0.0692**
- absolute maximum (brightest specular pixel) = **0.1329**

Re-measured on the black-and-white image (#886) with the neutral wallpaper
tokens from #885. Dark-theme tokens drawn directly on the photo, against p95
(WCAG AA body text needs 4.5:1; non-text UI needs 3:1):

| Token | Colour | Contrast vs p95 | vs brightest pixel |
| --- | --- | --- | --- |
| `textPrimary` | `#F5F5F4` | 8.07:1 | 5.26:1 |
| `textSecondary` (wallpaper) | `#D4D4D8` | 5.96:1 | 3.88:1 |
| `textMuted` (wallpaper) | `#C4C4CA` | 5.07:1 | 3.31:1 |
| link (wallpaper) | `#F5F5F4` | 8.07:1 | 5.26:1 |
| `success` | `#34D399` | 4.58:1 | 2.99:1 |
| `danger` (wallpaper) | `#FCA5A5` | 4.64:1 | 3.03:1 |
| field border (wallpaper) | `#9A9AA2` | 3.15:1 | — |
| checkbox border (wallpaper) | `#A1A1AA` | 3.44:1 | — |

The red logo mark (`#B3001B`) measures about 1.2:1 against the photo: it reads
by hue, not brightness. A logo has no WCAG contrast requirement, and Thomas
chose the deep red with this in view.

Field text sits on the opaque dark field fill `#1C1C1E`, not the photo:
`textSecondary` on that fill is 11.5:1 and `textPrimary` 15.6:1.

The wallpaper tokens live in `MayosPalette` (lightened from the dark theme) and
are applied only on the wallpapered screens via `MayosTheme.wallpaper`; the
signed-in app keeps the standard dark/light tokens.
