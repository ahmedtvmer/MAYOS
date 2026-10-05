# #249 production selected-family confirmation

These are separately labeled, unedited PNG captures of the current Flutter app
rendered in the widget test harness at phone-sized logical viewports. They use
real `MayosApp` screens, registered bundled fonts and Material icons, fake API
and store overrides, synthetic training/chat fixtures, and a fixed clock. No
private training data or hosted-model calls are involved.

## Captures

The 28 PNGs in `screens/` are 2× captures at text scale 1.0:

- Arabic Player Home, Home detail, logger, chat and scrolled chat detail at
  360×640 and 412×915 logical pixels in light and dark themes. The logger is
  captured before and after `27.5` keypad entry at both sizes and themes.
- Arabic RIR keypad and completed swipe stress views at 412×915 dark.
- English Home and logger at 412×915 light, through the same app seam.

Home detail is the actual exercise-detail screen for Bench Press; its muscle
and equipment chips remain English catalog data. Logger images show the
Material backspace icon with the localized semantic labels “Backspace” and
“حذف آخر رقم”, plus the Arabic header as title · timer with the timer isolated
left-to-right.

Chat detail is scrolled to the longer assistant reply containing Arabic and
English exercise names, Western numeric spans, Markdown headings, bold text,
lists and a blockquote. It differs from the corresponding chat capture. Logger stress
captures show the full Western-digit keypad and RIR choices `0 1 2 3 4 5+`;
the swipe view is taken after the completed end-to-start swipe removes the
first set.

The capture preserves the selected prototype's synthetic facts and copy where
the production app allows it: the Arabic program day, Wide-Grip Lat Pulldown
and Bench Press, 3 × 10 at RIR ≥ 2 with 120-second rests, 27.5 kg, 10 reps,
and the mixed Arabic/English assistant exchange with a Markdown quote. The
logger clock remains fixed at 2026-10-01 10:00 UTC. The same fixed clock is used
for workout elapsed time and the performed-date window, so the production
date-boundary notice does not intrude into the comparison captures.

`SHA256SUMS` contains one SHA-256 per PNG. The images are rendered directly
from Flutter widgets and have not been edited or recomposed.

## Font identities

Arabic Display language uses IBM Plex Sans Arabic static Regular, Medium,
SemiBold and Bold (weights 400, 500, 600 and 700) from `IBM/plex` commit
`763c36ef9117782905ae010056dfbe8fd2653a25`, font version 1.005. The upstream
SIL Open Font License 1.1 is retained at
[`mobile/assets/fonts/arabic/OFL-IBMPlex.txt`](../../../../mobile/assets/fonts/arabic/OFL-IBMPlex.txt).
Hashes for each bundled face and its license are recorded in
[`mobile/DESIGN.md`](../../../../mobile/DESIGN.md) and
[`docs/design-review/143/font-provenance.json`](../../143/font-provenance.json).

English display roles remain Playfair Display 1.203 and interface roles remain
Inter 4.001 (git `66647c0bb`). The logo artwork is unchanged; the small MAYOS
wordmark remains Inter. The visual English Home capture shows the serif display
heading, and widget checks assert the English role families.

## Reproduction

The source is in Git commit
[`1e28f040eb41378d374000dc1ca7ace35f7b9e14`](https://github.com/ahmedtvmer/MAYOS/commit/1e28f040eb41378d374000dc1ca7ace35f7b9e14),
the commit that adds this production evidence folder. Its parent is recorded in
[`BASE_COMMIT.txt`](BASE_COMMIT.txt). Check out that commit, then from the
repository root use Flutter 3.47.5 / Dart 3.13.4 as recorded in
`verification/flutter-version.log`:

```bash
git checkout --detach 1e28f040eb41378d374000dc1ca7ace35f7b9e14
cd mobile
flutter pub get --offline
CAPTURE_249=1 flutter test --no-pub --tags capture \
  test/visual/arabic_249_capture_test.dart --reporter expanded
cd ../docs/design-review/249/production/screens
sha256sum *.png > ../SHA256SUMS
```

Without `CAPTURE_249=1`, the capture test is skipped and does not write files.
The capture test's output path is `docs/design-review/249/production/screens/`.
The selected-family source, font assets, and capture harness are in that Git
commit; `BASE_COMMIT.txt` and this commit are the reproduction pointer.

## Verification and visual findings

See the logs in `verification/` and the gate summary in
[`../README.md`](../README.md). The capture review inspects wrapping, clipping
and ellipsis in the fixed Home, logger and chat fixtures. The longer Arabic
chat detail and mixed English exercise names wrap across lines and remain
visible at both widths. Headings, exercise names and chat text show no
unintended ellipsis. At 360×640, the logger's lower Add set control extends
partly below the viewport and remains reachable by scrolling; this is a
viewport boundary, not clipped text. The exercise detail image area has its
normal unavailable image placeholder in this offline fixture; exercise names
and details remain visible. Widget behavior checks separately prove `27.5`
keypad entry, stored weight and RIR, and set deletion in Arabic layout.

The logger keypad now renders `Icons.backspace_outlined` and exposes the
localized “Backspace” / “حذف آخر رقم” semantic label; the old unsupported
glyph is absent. The Arabic logger header reads title · timer with the timer
isolated LTR, while the English header remains “Log workout · mm:ss”. Home
detail is the exercise-detail screen, and its muscle/equipment chips remain
English catalog data.

The captured layouts cover Player screens at text scale 1.0 only. Coach-mode
and desktop visual states, OS keyboard states, accessibility text scales,
physical-device rendering and arbitrary future model/server text were not
captured. The fixed chat fixture exercises authored isolates and the current
paragraph direction heuristic; those mechanisms do not establish bidi support
for arbitrary future reply text. This is bounded typography confirmation, not
complete production-localization sign-off.
