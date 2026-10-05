# #249 — Selected Arabic typography acceptance review

This review evaluates the selected IBM Plex Sans Arabic confirmation published
with #143 against all twelve #249 acceptance criteria. It adds verification
records on the selected-source snapshot; it does not change the preserved
prototype or production code.

The [28 selected-family images](https://github.com/ahmedtvmer/MAYOS/tree/b9d1023db10f6164777c5b0136f1536cdf49b6a9/docs/design-review/143/selected)
are preserved at commit `b9d1023db10f6164777c5b0136f1536cdf49b6a9`. The original
A/B evidence remains separately preserved in the same #143 folder.

## Acceptance review

| # | Acceptance criterion | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Bundled IBM Plex faces fill Arabic type roles through shared theme; English fonts and brand remain; provenance and license retained. | **met** | `docs/design-review/143/selected/README.md`, `font-provenance.json`, `runtime-font-provenance.json`, `prototype-source.tar.gz` at `b9d1023`; source changes listed in `source-changes.json`. The selected override assigns the IBM Plex family through the shared typography boundary, and the original font assets and OFL licenses are retained. |
| 2 | Typography follows app version in Player, Coach and Flutter web; captures are representative Home/logger/chat only. | **met with limits** | `docs/design-review/143/selected/README.md` and `prototype.patch` at `b9d1023` identify the version-level typography selection and representative widget scope. The evidence does not provide separate visual sign-off for every mode or web surface. |
| 3 | Actual Flutter widgets render through fake API/store and capture seam, with real fonts/icons and no hosted inference or private fixture data. | **met** | `docs/design-review/143/README.md`, `selected/README.md`, and `selected/logs/capture-C.log` at `b9d1023`; the rerun passed all 8 checks in [capture.log](verification/capture.log). |
| 4 | 28 selected captures cover both phone sizes, themes, details, keypad, RIR and swipe stress views at scale 1.0 and 2×. | **partial** | `docs/design-review/143/selected/README.md`, `selected/SHA256SUMS`, and `selected/screens/` at `b9d1023`; [inventory](verification/published-capture-inventory.tsv) and [capture comparison](verification/capture-hash-comparison.txt) confirm all 28 names, dimensions and hashes. Each `C-chat-detail-{dark,light}-{360x640,412x915}.png` has the same SHA-256 as its matching `C-chat-{dark,light}-{360x640,412x915}.png`; the drag before the detail capture changes nothing, so those four files add no chat coverage. Home-detail images differ from their matching Home images. |
| 5 | Simple Arabic labels, English exercise names/RIR, readable wrapping and no unintended clipping/ellipsis. | **met with limits** | `docs/design-review/143/selected/README.md` and `screens/C-logger*.png` at `b9d1023`: logger day heading wraps to two lines at both widths; the published review records visual inspection for clipping and ellipsis. That inspection covers these fixed fixtures only. |
| 6 | RTL semantic layout; Arabic/English/mixed/Markdown readability; limits for bidi heuristics stated. | **met with limits** | `docs/design-review/143/README.md` (RTL corrections/limits) and `selected/README.md` at `b9d1023`. The fixture uses isolates and a first-letter direction heuristic; arbitrary future model/server text is not covered. |
| 7 | Western digits, LTR numeric values, keypad and RIR order. | **met** | `docs/design-review/143/selected/README.md`, `screens/C-logger-keypad*.png`, `screens/C-logger-rir-dark-412x915.png`, `selected/logs/capture-C.log` at `b9d1023`, and the passing rerun [capture.log](verification/capture.log). The capture assertions checked Western digits and order. |
| 8 | Real keypad entry of 27.5; logger interactions and directional swipe-delete verified. | **partial** | The C capture harness asserts that 27.5 appears after keypad entry and captures the RTL delete affordance on the left, but its swipe is held and then cancelled; it does not verify Arabic set persistence or a completed deletion. The 125-test [focused widget run](verification/widget-tests.log) used the default English build and verifies logger outcomes there. The existing logger behavior tests run with `ARABIC_PAIR=C` fail because they find widgets by English copy ([logger-arabic-C.log](verification/logger-arabic-C.log); 30 failures), so Arabic-build persistence and completed swipe deletion remain open. |
| 9 | English typography verified through the same app seam. | **met with limits** | In the default build, `workout_logger_screen_test.dart` checks the day-heading font family against `MayosTypography.displayFamily` and the “Log workout · mm:ss” label against `MayosTypography.uiFamily`; `mayos_markdown_test.dart` checks heading/code span families against those roles. The passing tests are in [widget-tests.log](verification/widget-tests.log). `lib/src/core/theme/mayos_typography.dart` in the selected source bundle switches those constants only for `ARABIC_PAIR == 'C'`, resolving them to Playfair Display / Inter in the default build. No English screen image was produced in this confirmation. `theme_and_shell_test.dart` checks theme/shell behavior and does not assert font families. |
| 10 | Semantic type hierarchy, Arabic 1.5 line height, zero tracking and heading wrapping. | **met** | `docs/design-review/143/README.md`, `prototype.patch`, and `selected/README.md` at `b9d1023` document the trial metrics and selected heading wrap. |
| 11 | Analysis and relevant Home, logger, chat, Markdown, theme/shell checks; distinguish baseline/environment; full suite not called passing if incomplete. | **met with limits** | [Analysis](verification/analyze.log) passed with no issues; the requested [focused widget run](verification/widget-tests.log) passed 125 tests. The [full suite](verification/full-suite.log) completed with 742 passed, approximately 207 skipped and 2 failures. Both failures reproduce on the original non-C source in [baseline-original-source.log](verification/baseline-original-source.log): the #54 documentation-link test lacks the docs tree in the source snapshot, and the older profile-update test fails in `profile_screen.dart`. These are baseline/snapshot failures; the full suite is complete but not green. |
| 12 | Separately labeled images, reproducible disposable source/patch bundle, identities, findings, reproduction, historical A/B and uncaptured states stated. | **met with limits** | `docs/design-review/143/README.md`, `selected/README.md`, selected source bundle and overrides, provenance manifests, `SHA256SUMS`, and [verification.json](verification/verification.json) at `b9d1023`; uncaptured states and production-localization limits are documented below. |


## Outcome and image coverage limits

The selected C capture proves keypad entry displays 27.5 and shows the RTL
delete affordance on the left. The swipe gesture is held for the stress image
and then cancelled; the C capture does not establish a committed deletion or
set persistence. The focused logger behavior tests ran in the default English
build and cover those outcomes through shared widget code. When the existing
logger behavior tests were run with `ARABIC_PAIR=C`, 30 failed because their
finders expect English labels; see [logger-arabic-C.log](verification/logger-arabic-C.log).
Arabic-build set persistence and completed swipe deletion therefore remain
unverified.

The four chat-detail images are byte-identical to their respective main chat
images: dark 360×640, dark 412×915, light 360×640 and light 412×915. The
capture's detail drag changes no visible content, so these images add no chat
coverage. The four Home-detail images differ from their corresponding Home
images. The selected set contains 28 files, but only the Home-detail set adds
distinct detail content beyond its main screen captures.

English family-role checks come from the default-build logger and Markdown
widget tests, not the theme/shell tests. In the selected source,
`lib/src/core/theme/mayos_typography.dart` maps those roles to Playfair Display
and Inter except when `ARABIC_PAIR == 'C'`. No English screen image was captured
for this confirmation.

## Fonts and provenance

Selected Arabic typography uses IBM Plex Sans Arabic static Regular, Medium,
SemiBold and Bold faces, pinned to `IBM/plex` commit
`763c36ef9117782905ae010056dfbe8fd2653a25` (font version 1.005). The upstream
OFL license is included as `OFL-IBMPlex.txt` in the preserved source bundle.
The selected family has no U+232B (`⌫`); the prototype uses
`Icons.backspace_outlined` with an Arabic semantic label instead.

The English roles remain Playfair Display (version 1.203) for display and Inter
(version 4.001; git `66647c0bb`) for interface text. Their exact identities and
hashes, and the Material Icons identity, are recorded in
`runtime-font-provenance.json` at `b9d1023`. IBM Plex and English assets are
not modified on this branch.

## Reproduction and new verification

The disposable source is the combined `prototype-source.tar.gz` and
`selected/selected-source-overrides.tar.gz` at commit
`b9d1023db10f6164777c5b0136f1536cdf49b6a9`. Reproduction steps are in
`selected/README.md` at that commit. The selected snapshot used here was already
extracted and had `flutter pub get` completed. Flutter was 3.47.5, framework
`6a19cca564`, Dart 3.13.4; the exact output is
[flutter-version.log](verification/flutter-version.log).

Flutter 3.47.5 / Dart 3.13.4 analysis completed with no issues. The selected-family capture harness passed all 8 checks and regenerated 28 PNGs. Every generated capture name, pixel size and SHA-256 hash matches the published selected set; see [capture.log](verification/capture.log) and [capture-hash-comparison.txt](verification/capture-hash-comparison.txt). The focused default-English Home, logger, Player chat, theme/shell and Markdown widget run passed 125 tests; see [widget-tests.log](verification/widget-tests.log). These logger behavior outcomes are not Arabic-build outcome checks: a separate run under `ARABIC_PAIR=C` failed 30 English-copy widget finders, recorded in [logger-arabic-C.log](verification/logger-arabic-C.log). The full `flutter test --no-pub` suite completed with 742 passed, approximately 207 skipped and 2 failures. [baseline-original-source.log](verification/baseline-original-source.log) shows the same failures on the original non-C source: one expects the absent docs tree in the snapshot, and one raises a `StateError` in the older profile-update test. The suite is complete but not green; these failures are not selected-override regressions.

Reproduce the fixed selected capture from the source snapshot as follows (use
an absolute scratch output directory):

```bash
cd <disposable-snapshot>/mobile
CAPTURE=1 CAPTURE_OUT=<scratch>/captures \
  flutter test --no-pub --dart-define=ARABIC_PAIR=C --tags capture \
  test/visual/arabic_143_capture_test.dart --reporter expanded
```

## Limits

This is bounded prototype evidence, not production localization. The fixtures
do not establish bidi behavior for arbitrary assistant/server text; the review's
paragraph heuristic and hand-authored isolates cover only the fixed examples.
Desktop layouts, OS keyboards, accessibility text scales, other screens,
production Display language, account persistence and production localization
remain uncaptured or out of scope. The selected captures represent the Arabic
Home, logger and Player assistant chat only.

## Production selected-family evidence

The production implementation and actual-widget captures are published in
[production/README.md](production/README.md), with 28 separately labeled PNGs
under [production/screens/](production/screens/) and their hashes in
[production/SHA256SUMS](production/SHA256SUMS). The earlier #143 A/B and
selected-family records above remain historical evidence and are unchanged.
This implementation and capture rerun close the prototype-only gaps as
follows:

| Criterion | Updated result | Production evidence |
| --- | --- | --- |
| 1 | **met** | The shared typography roles resolve to IBM Plex Sans Arabic when Display language is Arabic. English Playfair Display / Inter roles, brand artwork and the Inter wordmark remain. Font identities and license are recorded in `production/README.md`. |
| 2 | **met with limits** | The app selects theme typography from Display language rather than assistant reply language. The shared app theme is used by Player, Coach and web; captures are representative Player screens only. |
| 3 | **met** | The opt-in test renders `MayosApp` with fake API/store overrides, bundled fonts and Material icons. It uses fixed fixture data and makes no hosted-model calls. |
| 4 | **met** | The 28 images include Home, Home detail, logger before/after keypad entry, chat and scrolled chat detail at 360×640 and 412×915 in light and dark, plus the 412×915 dark RIR/swipe stress and English comparisons. All use text scale 1.0 and 2× output. The four new chat-detail captures differ from their matching chat captures. |
| 5 | **met with limits** | Headings, exercise names and chat text wrap without unintended ellipsis in the fixed captures. At 360×640, the logger's lower Add set control extends partly below the viewport and is reachable by scrolling. This checks only these fixtures, not arbitrary future content. |
| 6 | **met with limits** | RTL alignment and the logger's directional delete side are checked in the Arabic widget test; chat captures include Arabic, English names, numeric spans, Markdown and a quote. The fixed first-letter direction heuristic and authored isolates do not solve arbitrary future model/server text. |
| 7 | **met** | Captures show Western digits; the logger test checks physical keypad order, RIR order and `27.5` entry. |
| 8 | **met** | The Arabic widget test and stress capture confirm keypad entry stores 27.5, the set retains that value and RIR after editing, and a completed end-to-start swipe removes the set. The test checks that the delete background resolves to the left in RTL; the stress image shows the completed swipe result. |
| 9 | **met** | English Home and logger images use the same app/capture seam. Widget checks assert Playfair Display display roles and Inter interface roles remain selected for English. |
| 10 | **met** | Arabic roles keep the semantic size hierarchy, use line height 1.5 and zero tracking; the captures show long Arabic and English text at both phone widths. |
| 11 | **met with limits** | Flutter analysis reported no issues; the relevant Home/logger/chat/Markdown/theme-shell/typography files passed 156 tests, and the opt-in capture test passed 1 test. `ruff check .` passed. The full Flutter and Python suites were not run for this focused mobile change; see `production/verification/`. |
| 12 | **met with limits** | The image hashes, font identities and reproduction steps are published separately. The reproduction pointer is `production/BASE_COMMIT.txt` plus the Git commit that adds this production evidence folder. Desktop, OS keyboard and accessibility-scale states remain uncaptured; this is bounded confirmation, not complete production-localization sign-off. |

See [production/README.md](production/README.md) for the final gate results,
visual inspection findings, capture command and remaining limits.
