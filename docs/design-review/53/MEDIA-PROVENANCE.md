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
data, but they are relative filesystem paths — **not** URLs the mobile app can
load. The app does not bundle any of these files.

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
- Bundling or proxying the files would embed unverified third-party media in the
  product and make takedown/replacement costly.
- The `image_path`/`gif_path` values are relative and point at files the mobile
  app cannot fetch; turning them into absolute URLs would be inventing a media
  host.

## What is needed to enable images in production

1. Confirm the ExerciseDB licence (and any attribution requirements) for the
   exact media set shipped, and record it in this document.
2. Serve the rights-cleared media from an approved host (or bundle only the
   subset we are licensed to redistribute) and expose **absolute URLs** through
   the exercise-detail endpoint.
3. Set the build-time flag `--dart-define=MAYOS_EXERCISE_MEDIA=true`.

## Gate

The mobile app reads the flag in `mobile/lib/src/core/config.dart`
(`mayosExerciseMediaEnabled`), defaulting to OFF. The exercise-detail hero
builds an `Image` only when the flag is ON **and** the catalog detail carries a
loadable `http(s)` media URL (`ExerciseCatalogDetail.hasLoadableMedia`). Today
neither condition holds, so the hero is always the typographic/muscle-group
header and no `Image` widget is ever built on the exercise-detail screen.

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

- The media is served by the API's public `GET /media` route and ships in the
  Fly image (`data/images`, `data/videos`; `docs/DEPLOYMENT.md` §10.8).
- The exercise-detail hero shows the GIF first, falls back to the still image,
  caps its box at **180 × 180 logical pixels** (`contain`, so nothing is
  stretched), and carries the credit caption underneath; Settings → About →
  Credits holds the full notice and link.
- The logger thumbnail (#161) shows the still at 48 dp and, being tiny, may
  omit its own caption — the credit lives in the app.
- **Kill switch:** `--dart-define=MAYOS_EXERCISE_MEDIA=false` turns
  `mayosExerciseMediaEnabled` off, and then no catalog `Image` widget is built
  anywhere (the thumbnail shows its icon, the hero is the typographic header).
