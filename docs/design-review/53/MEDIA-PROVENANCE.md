# Exercise media provenance (#53)

This records what the repository actually contains for exercise imagery, what is
known and unknown about its licensing, and what is required before any exercise
image is shown in production.

## What the repo contains

- `data/exercises.json` (1,324 entries) — an ExerciseDB-derived catalog. Each
  entry carries `id`, `name`, `category`, `body_part`, `equipment`,
  `instructions` (a per-language map), `muscle_group`, `secondary_muscles`,
  `target`, `image`, `gif_url`, `media_id`, `created_at`, and `attribution`.
- `data/exercises.csv` — the ExerciseDB source export (includes the
  `gifUrl`/`image` fields and per-language `instructions/N` columns).
- `data/processed_exercises.csv` — the seed CSV the catalog database loads
  (`database/shared.py` `DEFAULT_CSV_PATH`). It stores `image_path`
  and `gif_path` as **local relative paths** (`images/0001-….jpg`,
  `videos/0001-….gif`) and English-only `instructions` text.
- `data/images/` (1,324 `.jpg`) and `data/videos/` (1,324 `.gif`) — the
  ExerciseDB-derived media files referenced by those relative paths.

The catalog database schema (`exercises.image_path`, `exercises.gif_path`) and
the new `GET /workouts/exercises/{id}` endpoint expose these paths as real
data, but they are relative paths, not full URLs. The mobile app resolves them
against its configured API base with `mediaUrlFor` as
`<API_BASE_URL>/media/<path>`; the app does not bundle the image or GIF files.

## What is known / unknown about the licensing

- **Known:** the media is ExerciseDB-derived. The source export's `attribution`
  field exists in `data/exercises.json`, but its contents have not been
  independently verified against a licence grant.
- **Unknown:** the licence terms covering the ExerciseDB images/GIFs and their
  exact attribution obligations are not documented anywhere in this repository.
  `docs/DEPLOYMENT.md` (~line 488) states that the production catalog CSV is
  operator-provided and "its licensing/provenance is unknown and this runbook
  invents none".

Because the licence is undocumented, MAYOS must **not** display this media in
production, and must not claim a licence it does not hold.

## Risks

- Displaying the media without a verified licence risks copyright infringement.
- Serving the files through the API exposes unverified third-party media in the
  product and can make takedown/replacement costly.
- The catalog paths depend on the API's `/media` route and configured API host;
  moving the storage backend must preserve that route or the mobile URL contract.

## Original pre-display checklist

Before the owner decision below, the checklist to enable display was:

1. Confirm the ExerciseDB licence (and any attribution requirements) for the
   exact media set shipped, and record it in this document. This remains
   pending for MAYOS.
2. Serve the media through an approved host while preserving the catalog's
   relative `image_path`/`gif_path` values. Issue #165 implements that storage
   location with private R2 objects streamed by the API.
3. Enable the media flag. It is ON by default; passing
   `--dart-define=MAYOS_EXERCISE_MEDIA=false` disables it.

## Gate

The mobile app reads the flag in `mobile/lib/src/core/config.dart`
(`mayosExerciseMediaEnabled`), which is ON by default. The exercise-detail hero
builds an `Image` when the catalog detail has a loadable media URL
(`ExerciseCatalogDetail.hasLoadableMedia`) and the flag is ON. The logger
thumbnail uses the catalog picture under the same flag. Passing
`--dart-define=MAYOS_EXERCISE_MEDIA=false` disables both surfaces.

## 2026-09-29 — Owner decision: display the media, pending MAYOS's licence

This section records the facts known on 2026-09-29 and the owner's decision
made that day. It supersedes the "must **not** display" conclusion above for
the current build; the earlier sections are kept as the record of what was
known before.

### Facts

- **The dataset's MIT `LICENSE` covers the data only.** It grants rights to
  the repository's data files; it does not licence the images and GIFs.
- **The source repository's `NOTICE.md` states** that the media is
  **© Gym visual**, and that it is redistributed in that source repository
  under the author's **separate written permission**.
- **That source repository grants no media rights.** Its permission to
  redistribute there does not extend to MAYOS: we hold no licence to the
  images or GIFs from it.
- **Gym visual's terms apply to any use** (site: `https://gymvisual.com/`),
  and require, on every use:
  - the credit **"© Gym visual — https://gymvisual.com/"**, and
  - the media shown **no larger than its native 180 × 180** — the files are
    used as-is, never scaled or stretched past 180 × 180 logical pixels.
- **MAYOS's own licence from Gym visual is pending.** Nothing here records
  that licence as held.

### Decision

The owner decided on **2026-09-29** to display the ExerciseDB/Gym visual
images and GIFs in the app **now, pending MAYOS's own licence from Gym
visual**, with Gym visual's terms honoured as above.

What that means in the build:

- The media is served by the API's public `GET /media` route from a private
  Cloudflare R2 bucket under `media/images/` and `media/videos/`. The bucket
  remains private; the API streams only the approved image/GIF paths and keeps
  the mobile app's existing URL contract. See `docs/DEPLOYMENT.md` §10.8.
- The media files are uploaded from `data/images/` and `data/videos/` using
  `scripts/upload_media_to_r2.py`. They are excluded from Fly's build context
  and no longer ship in the image.
- The exercise-detail hero shows the GIF first, falls back to the still image,
  caps its box at **180 × 180 logical pixels** (`contain`, so nothing is
  stretched), and carries the credit caption underneath; Settings → About →
  Credits holds the full notice and link.
- The logger thumbnail (#161) shows the still at 48 dp and, being tiny, may
  omit its own caption — the credit lives in the app.
- **Kill switch:** `--dart-define=MAYOS_EXERCISE_MEDIA=false` turns
  `mayosExerciseMediaEnabled` off, and then no catalog `Image` widget is built
  anywhere (the thumbnail shows its icon, the hero is the typographic header).
